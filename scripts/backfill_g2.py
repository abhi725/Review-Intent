"""Backfill G2 reviews from an Apify dataset that has already been paid for.

    python -m scripts.backfill_g2 9b0eQswNwawOdAVua           # Eventbrite, 25 reviews
    python -m scripts.backfill_g2 <dataset-id> --dry-run

Re-reading a stored Apify dataset is **free** — only running the actor costs
money. The Aug 1-2 runs left several datasets on the account holding real
event-ticketing reviews that were parsed by the old, buggy field mapping and
therefore stored without platform, country, sub-scores or switched-from.

This exists so the feed can be built and demonstrated against genuine data
without commissioning a new scrape, and so a mapping fix can be replayed over
history instead of only applying to reviews collected after the fix.

Rows already present are skipped: dedup is on (source, source_id).
"""

import asyncio
import sys
from datetime import datetime, timedelta, timezone

import httpx

from intentdesk import db
from intentdesk.config import settings
from intentdesk.services import signals

API = "https://api.apify.com/v2"

# Wide on purpose. The point is to load what was already collected, not to
# re-apply the collector's recency window to history.
MAX_AGE_DAYS = 3650


def _subscores(item: dict) -> dict:
    return {
        k: item[k]
        for k in ("easeOfUse", "easeOfSetup", "easeOfAdmin",
                  "qualityOfSupport", "meetsRequirements", "nps")
        if item.get(k) is not None
    }


async def fetch_dataset(dataset_id: str) -> list[dict]:
    if not settings.apify_token:
        raise SystemExit("APIFY_TOKEN is not set — cannot read the dataset")
    async with httpx.AsyncClient(timeout=90) as client:
        r = await client.get(
            f"{API}/datasets/{dataset_id}/items",
            headers={"Authorization": f"Bearer {settings.apify_token}"},
            params={"limit": 1000},
        )
        r.raise_for_status()
        return r.json()


async def main(dataset_id: str, dry_run: bool = False) -> None:
    items = await fetch_dataset(dataset_id)
    print(f"dataset {dataset_id}: {len(items)} items")

    cutoff = datetime.now(timezone.utc) - timedelta(days=MAX_AGE_DAYS)
    stored = repaired = skipped = undated = 0

    if not dry_run:
        await db.connect()

    for item in items:
        review_id = item.get("reviewId")
        if not review_id:
            skipped += 1
            continue

        published = item.get("publishedAt") or item.get("submittedAt")
        try:
            when = datetime.fromisoformat(str(published).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            undated += 1
            continue
        if when < cutoff:
            skipped += 1
            continue

        text = item.get("reviewText") or ""
        stars = item.get("starRating")
        switched = item.get("switchedFromOtherProduct")

        row = dict(
            kind="review",
            source="g2",
            source_id=f"g2:{review_id}",
            observed_at=when,
            quote=(item.get("title") or text)[:280],
            raw_text=text[:4000],
            url=item.get("url"),
            author=item.get("reviewerName"),
            rating=float(stars) if stars is not None else None,
            platform=item.get("productName"),
            source_site="g2",
            country=item.get("country"),
            region=item.get("region"),
            switched_from=switched if switched not in (None, "no") else None,
            switched_reason=item.get("switchedReason"),
            subscores=_subscores(item) or None,
        )

        if dry_run:
            print(f"  would store {row['source_id']} {row['rating']}* "
                  f"[{row['country']}] {row['platform']} — {row['quote'][:60]}")
            stored += 1
            continue

        if await signals.record(**row):
            stored += 1
        else:
            # Already stored — under the old, broken mapping, which is the
            # reason this script exists. Fill in what that mapping dropped.
            patched = await signals.update_provenance(
                source="g2",
                source_id=row["source_id"],
                platform=row["platform"],
                source_site="g2",
                country=row["country"],
                region=row["region"],
                switched_from=row["switched_from"],
                switched_reason=row["switched_reason"],
                subscores=row["subscores"],
                url=row["url"],
                author=row["author"],
                rating=row["rating"],
            )
            if patched:
                repaired += 1
            else:
                skipped += 1

    verb = "would store" if dry_run else "stored"
    print(f"{verb}={stored} repaired={repaired} skipped={skipped} "
          f"unparseable_date={undated}")

    if not dry_run:
        await db.disconnect()


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        raise SystemExit(__doc__)
    asyncio.run(main(args[0], dry_run="--dry-run" in sys.argv))
