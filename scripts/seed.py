"""Seed the watchlist, and optionally demo rows for developing the dashboard.

    python -m scripts.seed              # watchlist only (safe, real config)
    python -m scripts.seed --prune      # + delete competitors no longer tracked
    python -m scripts.seed --demo       # + fake leads on .example domains
    python -m scripts.seed --purge-demo # remove those fake rows

Demo companies all use .example domains, which are reserved by RFC 2606 and can
never be real. Nothing here contacts anyone.
"""

import asyncio
import sys
from datetime import datetime, timedelta, timezone

from intentdesk import db
from intentdesk.services import companies, leads, signals, watchlist

from intentdesk.market import COMPETITORS, RETIRED_COMPETITORS  # noqa: E402

now = datetime.now(timezone.utc)

DEMO = [
    {
        "name": "Sunburn Collective (demo)", "domain": "sunburn-collective.example",
        "city": "Pune", "vendor": "BookMyShow", "agents": 40, "score": 92,
        "contact": ("Priya Nair", "Head of Ticketing", None),
        "phone": "+91 20 4000 0001",
        "subject": "payouts after the gate closes",
        "body": "Hi Priya — most organisers running multi-city shows lose the "
                "week after an event to payout reconciliation and refund queues.\n\n"
                "We answer buyer calls and WhatsApp on event day so your team is "
                "not the switchboard.\n\nHow are you handling event-day volume now?",
        "signals": [
            ("job_post", "indeed", 6, 25, "Hiring a Ticketing Operations Executive; BookMyShow experience required."),
            ("review", "g2", 11, 30, "Per-ticket commission eats the margin on low-priced shows."),
            ("install", "csv_import", 120, 30, "BookMyShow checkout detected on the primary domain."),
        ],
    },
    {
        "name": "Bluepeak Conferences (demo)", "domain": "bluepeak.example",
        "city": "Ahmedabad", "vendor": "Explara", "agents": 18, "score": 84,
        "contact": ("Rohit Menon", "Events Manager", None),
        "phone": "+91 79 4000 0002",
        "subject": "check-in queues at the door",
        "body": "Hi Rohit — conference check-in is where a good event turns bad: "
                "one scanner down and the queue runs out of the door.\n\n"
                "We take the pre-event questions off your phone line so the team "
                "at the door is only doing the door.\n\nWhat does your event-day "
                "call volume look like?",
        "signals": [
            ("forum", "reddit", 3, 25, "Explara payouts held two weeks past the event; support unreachable."),
            ("install", "csv_import", 210, 30, "Explara registration widget on the events subdomain."),
        ],
    },
    {
        "name": "Kadam Arts Festival (demo)", "domain": "kadam-arts.example",
        "city": "Nashik", "vendor": "Townscript", "agents": 25, "score": 71,
        "contact": ("Anil Deshpande", "Festival Director", None),
        "phone": "+91 253 400 0003",
        "subject": "before the next on-sale",
        "body": "Hi Anil — festival buyers ask the same forty questions: gate "
                "timing, parking, refunds, whether the pass covers day two.\n\n"
                "We answer those in Marathi, Hindi and English so your team only "
                "handles what needs a person.\n\nWorth a look before your next "
                "on-sale?",
        "signals": [
            ("vendor_news", "google_news", 9, 15, "Townscript revises platform fees for the coming season."),
            ("install", "csv_import", 365, 30, "Townscript booking page linked from the festival site."),
        ],
    },
    {
        "name": "Silverline Venues (demo)", "domain": "silverline.example",
        "city": "Hyderabad", "vendor": "Eventbrite", "agents": 60, "score": 40,
        "contact": (None, None, None),
        "phone": None,
        "subject": None, "body": None,
        "signals": [("install", "csv_import", 240, 30, "Eventbrite checkout live. No complaint signal yet.")],
    },
]


async def seed_watchlist():
    for name, sources in COMPETITORS:
        await watchlist.add(name, sources)
    print(f"watchlist: {len(COMPETITORS)} competitors")


async def prune_watchlist():
    """Delete competitors from the abandoned helpdesk market.

    `watchlist.remove` only deactivates, which is right for a competitor you
    might come back to. These are from a different market entirely, and leaving
    them listed-but-off invites someone to switch them back on.
    """
    removed = []
    for name in RETIRED_COMPETITORS:
        result = await db.execute("DELETE FROM watchlist WHERE competitor = $1", name)
        if not result.endswith("0"):
            removed.append(name)
    # Anything active that is not in the current market is a leftover too.
    tracked = [c for c, _ in COMPETITORS]
    stale = await db.fetch(
        "SELECT competitor FROM watchlist WHERE competitor <> ALL($1::text[])", tracked
    )
    for row in stale:
        await db.execute("DELETE FROM watchlist WHERE competitor = $1", row["competitor"])
        removed.append(row["competitor"])
    print(f"pruned {len(removed)} off-market competitors: {', '.join(removed) or 'none'}")


async def seed_demo():
    for d in DEMO:
        co = await companies.upsert(
            name=d["name"], domain=d["domain"], vendor=d["vendor"],
            city=d["city"], agents_est=d["agents"],
        )
        if d.get("phone"):
            await db.execute(
                "UPDATE companies SET phone = $2 WHERE id = $1", co["id"], d["phone"]
            )
        for kind, source, age_days, weight, quote in d["signals"]:
            await signals.record(
                kind=kind, source=source,
                source_id=f"demo:{d['domain']}:{kind}:{source}",
                observed_at=now - timedelta(days=age_days),
                company_id=co["id"], quote=quote, weight=weight,
                matched_confidence=1.0,
            )
        name, title, email = d["contact"]
        await leads.upsert_lead(
            co["id"], d["score"],
            contact_name=name, contact_title=title, contact_email=email,
            enrich_source="demo" if (email or d.get("phone")) else None,
            draft_subject=d["subject"], draft_body=d["body"],
        )
    print(f"demo: {len(DEMO)} companies with signals and leads")


async def purge_demo():
    n = await db.fetchval(
        "WITH d AS (DELETE FROM companies WHERE domain LIKE '%.example' RETURNING 1) "
        "SELECT count(*) FROM d"
    )
    await db.execute("DELETE FROM suppression WHERE domain LIKE '%.example'")
    print(f"purged {n} demo companies (leads and signals cascade)")


async def main():
    await db.connect()
    try:
        if "--purge-demo" in sys.argv:
            await purge_demo()
        else:
            await seed_watchlist()
            if "--prune" in sys.argv:
                await prune_watchlist()
            if "--demo" in sys.argv:
                await seed_demo()
    finally:
        await db.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
