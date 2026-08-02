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
    ("BookMyShow", ["tech", "jobs", "reddit"]),
    ("Townscript", ["tech", "jobs", "reddit"]),
    ("Explara", ["tech", "jobs", "reddit"]),
    ("Paytm Insider", ["tech", "jobs", "reddit"]),
    ("MeraEvents", ["tech", "jobs", "reddit"]),
    ("Ticketmaster", ["tech", "jobs", "g2", "capterra", "reddit"]),
    ("Zoho Backstage", ["tech", "jobs", "g2", "capterra", "reddit"]),
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
    "MeraEvents": ("meraevents", "mera events"),
    "Ticketmaster": ("ticketmaster",),
    "Zoho Backstage": ("zoho backstage",),
}


# --------------------------------------------------------------- review sources
#
# The distinction that decides which of these are worth building: **who writes
# the review.** Our buyer is the organiser who pays for the platform. A site
# whose reviewers are ticket *buyers* produces complaints about refunds and
# queue times from people who will never buy anything from us.
#
# This is the same trap that killed Trustpilot for the earlier helpdesk market:
# a 1.7-star page that turned out to be angry end users, not customers.
#
#   status: "working"  — verified against the live API
#           "blocked"  — tried, fails on the current plan
#           "untried"  — plausible, not yet attempted
#           "wrong-audience" — reviewers are attendees, not organisers
REVIEW_SOURCES: dict[str, dict] = {
    # ---- organiser-facing B2B software review sites: the ones that matter ----
    "g2": {"audience": "organiser", "status": "working",
           "note": "Only Eventbrite/Ticketmaster/Zoho Backstage likely present; "
                   "Indian platforms have no G2 footprint"},
    "capterra": {"audience": "organiser", "status": "blocked",
                 "note": "403 to the pay-per-event actor; needs residential proxies"},
    "getapp": {"audience": "organiser", "status": "untried",
               "note": "Gartner-owned, same data pool as Capterra — expect the same blocking"},
    "software_advice": {"audience": "organiser", "status": "untried",
                        "note": "Also Gartner-owned; same caveat as GetApp"},
    "sourceforge": {"audience": "organiser", "status": "untried",
                    "note": "Less aggressively defended; worth a cheap try"},
    "product_hunt": {"audience": "organiser", "status": "untried",
                     "note": "Free official GraphQL API, but launch-era comments only — "
                             "thin for established platforms"},

    # ---- attendee-facing: high volume, wrong person ----
    "trustpilot": {"audience": "attendee", "status": "wrong-audience",
                   "note": "Reviewers are ticket buyers complaining about refunds"},
    "google_reviews": {"audience": "attendee", "status": "wrong-audience",
                       "note": "Local/consumer reviews; also needs the paid Places API"},
    "appsumo": {"audience": "organiser", "status": "wrong-audience",
                "note": "Only lists products that ran an AppSumo deal — none of "
                        "these did, so there is nothing to collect"},
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
