"""Delete signals about products that are no longer on the watchlist.

    python -m scripts.prune_stale             # show what would go
    python -m scripts.prune_stale --apply     # delete it

The pivot from helpdesk to event ticketing deleted four competitors from
`market.COMPETITORS`, but the reviews already collected about them stayed in the
database. Nine G2 reviews of Freshdesk, Zoho Desk and Zendesk were still the
newest rows in the feed on 2026-08-03 — so the first thing the signal feed
showed was complaints about a market this product no longer serves.

Matched on `RETIRED_COMPETITORS` rather than "anything not in COMPETITORS", so a
signal that simply has not been attributed to a platform yet is never swept up
by a rename or a collector that forgot to set `platform`.
"""

import asyncio
import sys

from intentdesk import db
from intentdesk.market import RETIRED_COMPETITORS


async def main(apply: bool = False) -> None:
    await db.connect()

    # `platform` is NULL on everything stored before migration 006, so the text
    # of the review is the only evidence of what it was about. Both are checked.
    patterns = [f"%{name}%" for name in RETIRED_COMPETITORS]

    rows = await db.fetch(
        """
        SELECT id, source, source_id, platform, observed_at,
               left(coalesce(quote, raw_text, ''), 70) AS preview
        FROM signals
        WHERE platform ILIKE ANY($1::text[])
           OR quote     ILIKE ANY($1::text[])
           OR raw_text  ILIKE ANY($1::text[])
        ORDER BY observed_at DESC
        """,
        patterns,
    )

    print(f"retired competitors: {', '.join(RETIRED_COMPETITORS)}")
    print(f"matching signals: {len(rows)}\n")
    for r in rows:
        print(f"  {r['id']:>5} {r['source']:<12} {str(r['platform'] or '-'):<12} "
              f"{r['observed_at']:%Y-%m-%d} {r['preview']}")

    if not rows:
        print("\nnothing to prune")
    elif apply:
        deleted = await db.execute(
            """
            DELETE FROM signals
            WHERE platform ILIKE ANY($1::text[])
               OR quote     ILIKE ANY($1::text[])
               OR raw_text  ILIKE ANY($1::text[])
            """,
            patterns,
        )
        print(f"\ndeleted: {deleted}")
    else:
        print("\ndry run — pass --apply to delete")

    await db.disconnect()


if __name__ == "__main__":
    asyncio.run(main(apply="--apply" in sys.argv))
