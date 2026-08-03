"""One-off repair: replace assumed countries with observed ones.

Every company promoted before 2026-08-03 was written with a hardcoded
`country="IN"` (and its install signal with `"India"`), which was true while
MeraEvents was the only discovery source and false once Eventbrite was added.
See `tests/test_country_truthfulness.py` for the defect; this fixes the rows it
already produced.

Free — `organizations/search` is on Apollo's free plan. Read-mostly: it only
writes where Apollo actually reports a country, so a company Apollo does not
know keeps whatever it has rather than being blanked on no evidence.

**Only companies discovered on a global platform are touched.** The dry run
found Apollo reporting `4moles.com` as Thailand; it is an Indian golf business
sitting on MeraEvents' organiser sitemap, and that sitemap membership is direct
evidence of operating in India, while Apollo's answer is a name match that can
land on a different company entirely. Where the two disagree about a company
found on an India-only platform, the sitemap wins — so "correcting" those rows
would trade one wrong country for another. `market.BRANDS[...]["region"]`
decides which platforms qualify; for Eventbrite, a global platform, the sitemap
implies nothing about location and Apollo is the only evidence there is.

    python -m scripts.repair_country            # report only
    python -m scripts.repair_country --write    # apply

Deliberately not wired into the app or the cron. A backfill that runs itself is
a backfill nobody can date afterwards.
"""

import asyncio
import sys

from intentdesk import db, market
from intentdesk.services.resolving import apollo_search, is_india


def platform_implies_india(vendor: str) -> bool:
    """True when discovery itself is location evidence, so Apollo must not
    override it."""
    return market.BRANDS.get(vendor, {}).get("region") == "IN"


async def main(write: bool) -> None:
    await db.connect()
    rows = await db.fetch(
        """
        SELECT id, name, domain, city, country, vendor, discovered_via
        FROM companies
        WHERE discovered_via IS NOT NULL
        ORDER BY id
        """
    )
    print(f"{len(rows)} discovered companies\n")

    changed = confirmed = unknown = skipped = 0
    for row in rows:
        if platform_implies_india(row["vendor"] or ""):
            skipped += 1
            print(f"  [sitemap    ] {row['name'][:38]:40} on {row['vendor']} (India-only) — left alone")
            continue

        hit = await apollo_search(row["name"])
        reported = (hit or {}).get("country_name") or (hit or {}).get("country_code")
        if not reported:
            unknown += 1
            print(f"  [no country ] {row['name'][:38]:40} keeping {row['country']!r}")
            continue

        verdict = is_india((hit or {}).get("country_code"), (hit or {}).get("country_name"))
        observed = reported.strip()
        if (row["country"] or "").strip().lower() == observed.lower():
            confirmed += 1
            print(f"  [confirmed  ] {row['name'][:38]:40} {observed}")
            continue

        flag = "" if verdict else "  <-- not India"
        print(f"  [CORRECT    ] {row['name'][:38]:40} {row['country']!r} -> {observed!r}{flag}")
        changed += 1
        if write:
            await db.execute("UPDATE companies SET country = $2 WHERE id = $1",
                             row["id"], observed)
            await db.execute(
                "UPDATE signals SET country = $2 WHERE company_id = $1 AND kind = 'install'",
                row["id"], observed,
            )

    print(f"\n{confirmed} already correct, {changed} "
          f"{'corrected' if write else 'to correct'}, {unknown} unknown to Apollo, "
          f"{skipped} trusted from an India-only sitemap")
    if not write and changed:
        print("Re-run with --write to apply.")


if __name__ == "__main__":
    asyncio.run(main(write="--write" in sys.argv))
