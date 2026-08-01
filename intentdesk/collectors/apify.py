"""Apify-backed collectors.

A note on what G2 actually gives you: a review carries `reviewerName` as a
first name and last initial ("Irfan M."), with industry and company segment as
numeric codes. There is no company name and no domain. So these signals almost
always land *unmatched* — they are market intelligence and a source of
complaint language, not a source of leads. Leads come from the install base.

Verified against the live API on 2026-08-01: slugs below are real, and the
account is on the FREE plan with a $5/month ceiling, so every run is capped.
"""

import asyncio
from datetime import datetime, timedelta, timezone

import httpx

from intentdesk.collectors import Collector, RawSignal
from intentdesk.config import settings

API = "https://api.apify.com/v2"

# Verified live. G2 renamed the Zendesk product, which is why the obvious guess
# "zendesk-support-suite" 404s.
G2_SLUGS = {
    "zendesk": "zendesk-for-customer-service",
    "freshdesk": "freshdesk",
    "zoho desk": "zoho-desk",
    "kayako": "kayako",
}

NEGATIVE_AT_OR_BELOW = 3  # stars out of 5
RECENCY_DAYS = 180


class ApifyRunner:
    """Start an actor, wait for it, return items. Records what the run cost."""

    def __init__(self, token: str):
        self.token = token

    async def run(self, actor: str, payload: dict, timeout_s: int = 240) -> tuple[list[dict], float]:
        headers = {"Authorization": f"Bearer {self.token}"}
        async with httpx.AsyncClient(timeout=60) as client:
            start = await client.post(
                f"{API}/acts/{actor}/runs", headers=headers, json=payload
            )
            start.raise_for_status()
            run = start.json()["data"]
            run_id, dataset_id = run["id"], run["defaultDatasetId"]

            waited = 0
            status = run["status"]
            while status in ("READY", "RUNNING") and waited < timeout_s:
                await asyncio.sleep(5)
                waited += 5
                poll = await client.get(f"{API}/actor-runs/{run_id}", headers=headers)
                poll.raise_for_status()
                status = poll.json()["data"]["status"]

            detail = (await client.get(f"{API}/actor-runs/{run_id}", headers=headers)).json()["data"]
            cost = float(detail.get("usageTotalUsd") or 0)

            if status != "SUCCEEDED":
                raise RuntimeError(f"{actor} finished as {status} after {waited}s")

            items = await client.get(
                f"{API}/datasets/{dataset_id}/items", headers=headers, params={"limit": 1000}
            )
            items.raise_for_status()
            return items.json(), cost


class G2ReviewCollector(Collector):
    name = "apify_g2"
    kind = "review"
    requires = ("apify_token",)
    actor = "automation-lab~g2-scraper"

    # 25 rather than 100: a full scan of four competitors at 50 each cost $1.41
    # against a $5/month account, which would allow only three scans a month.
    def __init__(self, max_reviews: int = 25):
        self.max_reviews = max_reviews
        self.last_cost_usd = 0.0

    async def collect(self, competitor: str) -> list[RawSignal]:
        slug = G2_SLUGS.get(competitor.strip().lower())
        if not slug:
            return []  # not a product we have a verified slug for

        items, cost = await ApifyRunner(settings.apify_token).run(
            self.actor,
            {
                "mode": "product_reviews",
                "productUrls": [slug],
                "maxReviews": self.max_reviews,
                "sortReviews": "newest",
            },
        )
        self.last_cost_usd = cost

        cutoff = datetime.now(timezone.utc) - timedelta(days=RECENCY_DAYS)
        out: list[RawSignal] = []

        for item in items:
            stars = item.get("starRating")
            if stars is None or stars > NEGATIVE_AT_OR_BELOW:
                continue

            published = item.get("publishedAt") or item.get("submittedAt")
            try:
                when = datetime.fromisoformat(str(published).replace("Z", "+00:00"))
            except (TypeError, ValueError):
                continue
            if when < cutoff:
                continue

            text = item.get("reviewText") or ""
            out.append(
                RawSignal(
                    kind="review",
                    source="g2",
                    source_id=f"g2:{item.get('reviewId')}",
                    observed_at=when,
                    quote=(item.get("title") or text)[:280],
                    raw_text=text[:4000],
                    vendor=competitor,
                    # G2 exposes no company or domain, so this stays unmatched
                    # unless the reviewer happens to name their employer.
                    company_name=None,
                    company_domain=None,
                )
            )

        return out


class CapterraReviewCollector(Collector):
    """Capterra via a pay-per-event actor.

    `imadjourney/capterra-reviews-scraper` was in the original plan but is
    $25/month flat, which does not fit a $5 account, so this uses gio21's
    pay-per-event actor instead.
    """

    name = "apify_capterra"
    kind = "review"
    requires = ("apify_token",)
    actor = "gio21~capterra-reviews-scraper"

    def __init__(self, max_items: int = 20):
        self.max_items = max_items
        self.last_cost_usd = 0.0

    async def collect(self, competitor: str) -> list[RawSignal]:
        items, cost = await ApifyRunner(settings.apify_token).run(
            self.actor, {"query": competitor, "maxItems": self.max_items}
        )
        self.last_cost_usd = cost

        # Verified 2026-08-01: Capterra returns 403 to this actor's datacenter
        # proxies, and the run still exits SUCCEEDED with a warning row. Left
        # silent, that is indistinguishable from "no negative reviews found",
        # so it is escalated to an error the scan report will show.
        if len(items) == 1 and "warning" in items[0]:
            raise RuntimeError(
                f"capterra blocked the scrape ({items[0]['warning']}) — the actor "
                "needs residential proxies, which the free Apify plan does not include"
            )

        cutoff = datetime.now(timezone.utc) - timedelta(days=RECENCY_DAYS)
        out: list[RawSignal] = []

        for item in items:
            rating = item.get("rating") or item.get("overallRating")
            try:
                rating = float(rating)
            except (TypeError, ValueError):
                continue
            if rating > NEGATIVE_AT_OR_BELOW:
                continue

            published = item.get("publishedAt") or item.get("date") or item.get("reviewDate")
            try:
                when = datetime.fromisoformat(str(published).replace("Z", "+00:00"))
            except (TypeError, ValueError):
                continue
            if when.tzinfo is None:
                when = when.replace(tzinfo=timezone.utc)
            if when < cutoff:
                continue

            ident = item.get("reviewId") or item.get("id") or item.get("url")
            text = item.get("cons") or item.get("reviewText") or item.get("text") or ""
            out.append(
                RawSignal(
                    kind="review",
                    source="capterra",
                    source_id=f"capterra:{ident}",
                    observed_at=when,
                    quote=str(text)[:280],
                    raw_text=str(text)[:4000],
                    vendor=competitor,
                )
            )

        return out
