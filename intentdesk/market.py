"""What market we sell into.

Everything market-specific lives here — competitors, complaint taxonomy,
technology markers, and the language the prompts use. The pipeline itself is
market-neutral, so switching targets is an edit to this file rather than a hunt
through prompts, collectors and seeds.

Current market: **event ticketing** (confirmed 2026-08-02). The project was
built against helpdesk ticketing first; that assumption is what this file
replaced.
"""

MARKET = "event ticketing"

# Platforms an Indian SME event organiser would plausibly be on. Adjust freely
# — the watchlist is data, and `python -m scripts.seed` re-applies this list.
COMPETITORS: list[tuple[str, list[str]]] = [
    ("Eventbrite", ["tech", "jobs", "g2", "capterra", "reddit", "vendor_news"]),
    ("BookMyShow", ["tech", "jobs", "g2", "reddit"]),
    ("Townscript", ["tech", "g2", "capterra"]),
    ("Explara", ["tech", "g2", "capterra"]),
    ("Paytm Insider", ["tech", "jobs", "reddit"]),
    ("Ticket Tailor", ["tech", "g2", "capterra"]),
]

# What organisers actually complain about. Used as the enum the analyser must
# choose from, so keep it short and non-overlapping.
COMPLAINT_CATEGORIES = [
    "high_fees",              # per-ticket or service fees
    "payout_delay",           # money held after the event
    "refund_handling",        # cancellations, chargebacks
    "checkin_problems",       # scanning and door entry
    "poor_support",           # nobody answers on event day
    "limited_customization",  # branding, page design
    "integration_gaps",       # CRM, marketing, accounting
    "reporting_gaps",         # attendee data and analytics
    "reliability",            # outages, especially at on-sale
]

# Substrings that identify a ticketing platform in a technology list. Matching
# is case-insensitive substring, so these must be distinctive: a bare "insider"
# would match unrelated products, which is why the full brand is used.
VENDOR_MARKERS: dict[str, tuple[str, ...]] = {
    "Eventbrite": ("eventbrite",),
    "BookMyShow": ("bookmyshow", "book my show"),
    "Townscript": ("townscript",),
    "Explara": ("explara",),
    "Paytm Insider": ("paytm insider",),
    "Ticket Tailor": ("ticket tailor", "tickettailor"),
}

# G2 product slugs, discovered via the scraper's search mode on 2026-08-02.
# Guessing a slug returns "product not found" and a silent zero, so only
# verified entries belong here.
#
# Finding worth keeping: of the watchlist above, **only Eventbrite has a real
# G2 presence** (910 reviews). BookMyShow, Townscript, Explara and Paytm
# Insider returned nothing — G2 is a US/global B2B review site and India's
# ticketing platforms are not reviewed there. For those, G2 is not a usable
# signal source and the value has to come from tech detection, forums, job
# postings, and app-store reviews instead.
G2_SLUGS: dict[str, str] = {
    "eventbrite": "eventbrite",
}

# Global event-management platforms that *do* have G2 presence, surfaced by the
# same search. Add any that are genuinely competitors and their slug becomes
# usable immediately: cvent-event-marketing-management, vfairs, whova, zeffy.
G2_CANDIDATES_UNCONFIRMED = [
    "cvent-event-marketing-management",
    "vfairs",
    "whova",
    "zeffy",
]

# Wording the prompts use, so market language lives beside the market.
BUYER_ROLE = "event organiser"
PLATFORM_NOUN = "event ticketing platform"
SIZE_NOUN = "events run per year"
