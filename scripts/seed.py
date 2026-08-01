"""Seed the watchlist, and optionally demo rows for developing the dashboard.

    python -m scripts.seed              # watchlist only (safe, real config)
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

COMPETITORS = [
    ("Zendesk", ["tech", "jobs", "g2", "capterra", "reddit", "vendor_news"]),
    ("Freshdesk", ["tech", "jobs", "g2", "capterra", "reddit", "vendor_news"]),
    ("Zoho Desk", ["tech", "jobs", "g2", "capterra"]),
    ("Kayako", ["tech", "g2"]),
]

now = datetime.now(timezone.utc)

DEMO = [
    {
        "name": "Acme Retail (demo)", "domain": "acme-retail.example", "city": "Pune",
        "vendor": "Zendesk", "agents": 40, "score": 92,
        "contact": ("Priya Nair", "Head of Customer Experience", "priya@acme-retail.example"),
        "subject": "40 agents, or 12?",
        "body": "Hi Priya — most retail support teams add headcount because their "
                "helpdesk bills per agent, not because the tickets need people.\n\n"
                "We put AI voice and WhatsApp on the front line so the routine 60% "
                "never reaches an agent.\n\nWorth fifteen minutes on your volume?",
        "signals": [
            ("job_post", "naukri", 6, 25, "Hiring a Zendesk Administrator across two support centres."),
            ("review", "g2", 11, 30, "Per-agent pricing means every seasonal hire costs us twice."),
            ("install", "builtwith", 120, 30, "Zendesk widget live on the primary domain."),
        ],
    },
    {
        "name": "Bluepeak Logistics (demo)", "domain": "bluepeak.example", "city": "Ahmedabad",
        "vendor": "Freshdesk", "agents": 18, "score": 84,
        "contact": ("Rohit Menon", "IT Manager", "rohit@bluepeak.example"),
        "subject": "When the next tier costs more than the problem",
        "body": "Hi Rohit — logistics support runs on a handful of repeated questions.\n\n"
                "We handle those on voice and WhatsApp before they become tickets.\n\n"
                "Open to a short call this week?",
        "signals": [
            ("forum", "reddit", 3, 25, "Automations cap out and the next tier triples the bill."),
            ("install", "builtwith", 210, 30, "Freshdesk portal on the support subdomain."),
        ],
    },
    {
        "name": "Kadam Health (demo)", "domain": "kadam-health.example", "city": "Nashik",
        "vendor": "Zendesk", "agents": 25, "score": 71,
        "contact": ("Anil Deshpande", "Operations Head", "anil@kadam-health.example"),
        "subject": "Before your renewal lands",
        "body": "Hi Anil — clinics get the same fifty questions a day: appointment "
                "timing, report status, insurance paperwork.\n\nWe answer those in "
                "Marathi, Hindi and English so your team handles only what needs a person.",
        "signals": [
            ("vendor_news", "vendor_news", 9, 15, "Zendesk Suite price revision at next renewal."),
            ("install", "builtwith", 365, 30, "Zendesk Guide help centre detected."),
        ],
    },
    {
        "name": "Silverline Pharma (demo)", "domain": "silverline.example", "city": "Hyderabad",
        "vendor": "Zendesk", "agents": 60, "score": 40,
        "contact": (None, None, None),
        "subject": None, "body": None,
        "signals": [("install", "builtwith", 240, 30, "Zendesk Suite live. No complaint signal yet.")],
    },
]


async def seed_watchlist():
    for name, sources in COMPETITORS:
        await watchlist.add(name, sources)
    print(f"watchlist: {len(COMPETITORS)} competitors")


async def seed_demo():
    for d in DEMO:
        co = await companies.upsert(
            name=d["name"], domain=d["domain"], vendor=d["vendor"],
            city=d["city"], agents_est=d["agents"],
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
            enrich_source="demo" if email else None,
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
            if "--demo" in sys.argv:
                await seed_demo()
    finally:
        await db.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
