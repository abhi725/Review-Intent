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
    ("Ticket Tailor", ["tech", "jobs", "g2", "reddit"]),
]

# Competitors from the abandoned helpdesk market. `python -m scripts.seed
# --prune` deletes any watchlist row not in COMPETITORS above; this list exists
# so the deletion is a named decision rather than a silent diff.
RETIRED_COMPETITORS = ("Zendesk", "Freshdesk", "Zoho Desk", "Kayako")

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
    "Ticket Tailor": ("ticket tailor", "tickettailor"),
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

# Subreddits worth searching. The audience rule from REVIEW_SOURCES applies
# here too and is easy to get wrong: r/festivals and r/aves are full of ticket
# buyers venting about queues and refunds, which reads like rich signal and is
# the wrong person entirely. These are the organiser-side communities.
SUBREDDITS = (
    "eventplanning",
    "EventProduction",
    "Entrepreneur",
    "smallbusiness",
    "IndiaBusiness",
    "StartUpIndia",
)

# Deliberately excluded — attendee communities, kept here so nobody adds them
# back thinking they were an oversight.
SUBREDDITS_WRONG_AUDIENCE = ("festivals", "aves", "Music", "India")

# Reddit access, tested 2026-08-02 — cost $0.24 of the Apify budget to learn:
#
# 1. Direct, unauthenticated: blocked on every path from this VM.
#    search.json 403, search.rss 200-but-empty, new.rss 429.
# 2. Apify `trudax/reddit-scraper-lite` (pay-per-event, works on the free
#    plan): runs fine but is **global-search only**. Both scoping methods
#    return zero — `searchCommunityName` and a subreddit search `startUrls`.
#    A global search for "eventbrite" returned 10 posts, 7 mentioning it, and
#    **0 usable organiser complaints**: the hits were people *advertising*
#    events on Eventbrite plus an unrelated scam warning.
#
# Conclusion: paying to scrape Reddit globally buys noise. The value is in
# subreddit-scoped search, and only the official API can do that — which needs
# the free OAuth app credentials the collector already expects. Do not spend
# more Apify budget here.
REDDIT_ACCESS_NOTE = "official API only; Apify global search yields no usable signal"

# --------------------------------------------------------------- job postings
#
# Tried and rejected 2026-08-02, for $0.042. The theory was that a posting
# naming the platform proves an active install *and* budget, and that unlike G2
# and Reddit it carries a company identity. Both halves failed against the live
# API: Indeed matches job titles rather than description text, so a vendor-name
# search returns FOUND_NO_RESULTS, and `parseCompanyDetails` returns no employer
# website. See intentdesk/collectors/jobs.py for the full finding.
#
# Do not re-run vendor-name job searches. Kept here so the query that was tried
# is on the record.
JOB_QUERY_TEMPLATE = '"{competitor}"'

# Roles that indicate the platform is operated, not merely mentioned in passing.
JOB_ROLE_TERMS = (
    "event", "ticketing", "box office", "operations", "marketing",
    "community", "venue", "festival", "conference", "registration",
)

# Where to look. Indeed's India domain covers the SME market better than
# LinkedIn, whose postings skew enterprise.
JOB_LOCATIONS = ("India",)


# ---------------------------------------------------------------- vendor news
#
# Google News RSS needs no key and no Apify credit, which is why it replaced the
# vendor blog feeds from the original plan — those 404'd. The query is
# deliberately narrow: a bare vendor name returns event listings and funding
# gossip, neither of which says anything about a customer's willingness to move.
NEWS_RSS = (
    "https://news.google.com/rss/search"
    "?q={query}&hl=en-IN&gl=IN&ceid=IN:en"
)

# What actually predicts churn. A price rise or an outage is a reason to look
# around; a product launch is not.
NEWS_TRIGGER_TERMS = (
    "price", "pricing", "fee", "fees", "increase", "hike", "raises prices",
    "outage", "down", "downtime", "breach", "data breach", "lawsuit",
    "layoff", "layoffs", "shuts down", "shutting down", "discontinue",
    "acquisition", "acquired", "sunset",
)


# Wording the prompts use, so market language lives beside the market.
BUYER_ROLE = "event organiser"
PLATFORM_NOUN = "event ticketing platform"
SIZE_NOUN = "events run per year"

# The default pitch. This is a **placeholder written by the tool, not by the
# business** — it is the one input no amount of code can supply, and every draft
# inherits it. Override it in Settings; `value_proposition_is_default()` reports
# whether anyone has, so the dashboard can say so out loud.
DEFAULT_VALUE_PROPOSITION = (
    "AI voice and WhatsApp agents that answer ticket buyers on event day, so "
    "organisers stop losing sales to unanswered calls"
)

# Pitches that were typed to get past the empty field, including this tool's own
# defaults across both markets. Anything here still counts as "nobody has written
# the real one yet" — a stored placeholder is not the same as a decision.
PLACEHOLDER_VALUE_PROPOSITIONS = (
    DEFAULT_VALUE_PROPOSITION,
    "AI voice + WhatsApp at SME pricing",
    "AI voice and WhatsApp on the front line, so routine tickets never reach an agent",
)
