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

# ------------------------------------------------------------------ segments
#
# The single most expensive thing to get wrong about a review source, and it is
# a property of the *brand*, not the site. Proven against live data 2026-08-03:
# Eventbrite's Trustpilot page was 20/20 ticket buyers; Ticket Tailor's, on the
# same site with the same scraper at the same price, returned real organisers.
#
#   organiser_saas        — sold to the organiser, so its reviewers are our buyer
#   consumer_marketplace  — sold to the attendee, so its reviewers are not
#
# A paid review run against a consumer_marketplace brand is money spent
# collecting complaints from people who will never buy anything from us.
SEGMENTS = ("organiser_saas", "consumer_marketplace")

# ------------------------------------------------------------------- brands
#
# One entry per competitor, and the single source of truth: the watchlist rows,
# the G2 slug map and the Trustpilot allow-list are all derived from it below,
# so a brand cannot be tracked in one place and missing from another.
#
# `trustpilot_url` and `g2_slug` are **hand-verified or absent**. There is no
# name search: `ti.to` name-matched Tito-Express, a German printer-ink retailer,
# and returned twelve reviews about undelivered toner cartridges. None means
# "nobody has checked", and the collector skips rather than guessing.
#
# `active` False means registered but not scanned. Turning a brand on multiplies
# what every paid run costs, so the expansion set ships off and is switched on
# deliberately.
BRANDS: dict[str, dict] = {
    # ---------------------------------------------- India, the primary market
    "Eventbrite": {
        "sources": ["tech", "jobs", "g2", "capterra", "reddit", "vendor_news"],
        "segment": "consumer_marketplace",
        "region": "global",
        "active": True,
        "g2_slug": "eventbrite",
        "trustpilot_url": "https://www.trustpilot.com/review/eventbrite.com",
        # Verified live and kept deliberately, with the finding attached: the
        # page is real, the reviewers are the wrong people. Recording that is
        # what stops it being re-tried every quarter.
        "trustpilot_note": "verified 2026-08-03; 20/20 negative reviews were "
                           "ticket buyers, not organisers — do not spend here again",
    },
    "BookMyShow": {
        "sources": ["tech", "jobs", "reddit"],
        "segment": "consumer_marketplace",
        "region": "IN",
        "active": True,
    },
    "Townscript": {
        "sources": ["tech", "jobs", "reddit"],
        "segment": "organiser_saas",
        "region": "IN",
        "active": True,
    },
    "Explara": {
        "sources": ["tech", "jobs", "reddit"],
        "segment": "organiser_saas",
        "region": "IN",
        "active": True,
    },
    "Paytm Insider": {
        "sources": ["tech", "jobs", "reddit"],
        "segment": "consumer_marketplace",
        "region": "IN",
        "active": True,
    },
    "MeraEvents": {
        "sources": ["tech", "jobs", "reddit"],
        "segment": "organiser_saas",
        "region": "IN",
        "active": True,
    },
    "Ticketmaster": {
        "sources": ["tech", "jobs", "g2", "capterra", "reddit"],
        "segment": "consumer_marketplace",
        "region": "global",
        "active": True,
    },
    "Zoho Backstage": {
        "sources": ["tech", "jobs", "g2", "capterra", "reddit"],
        "segment": "organiser_saas",
        "region": "IN",
        "active": True,
    },
    "Ticket Tailor": {
        "sources": ["tech", "jobs", "g2", "reddit", "trustpilot"],
        "segment": "organiser_saas",
        "region": "global",
        "active": True,
        "trustpilot_url": "https://www.trustpilot.com/review/tickettailor.com",
        "trustpilot_note": "verified 2026-08-03; 3 of 12 were genuine organiser "
                           "complaints — the best yield of any brand tried",
    },

    # -------------------------------- expansion set: registered, not yet on
    #
    # Organiser-facing by segment, which is why these and not the marketplaces.
    # Each still needs its Trustpilot page checked by hand before a paid run —
    # exactly the Tito-Express lesson — so they carry no URL yet.
    "Weezevent": {
        "sources": ["tech", "reddit", "trustpilot"],
        "segment": "organiser_saas",
        "region": "FR",
        "active": False,
        "trustpilot_url": "https://www.trustpilot.com/review/weezevent.com",
        "trustpilot_note": "verified 2026-08-03; 12 reviews, all French consumers "
                           "chasing refunds — right segment, wrong audience in practice",
    },
    "Humanitix": {
        "sources": ["tech", "g2", "reddit"],
        "segment": "organiser_saas",
        "region": "AU",
        "active": False,
    },
    "Billetto": {
        "sources": ["tech", "reddit"],
        "segment": "organiser_saas",
        "region": "EU",
        "active": False,
    },
    "Eventix": {
        "sources": ["tech", "reddit"],
        "segment": "organiser_saas",
        "region": "EU",
        "active": False,
    },
    "Cvent": {
        "sources": ["tech", "jobs", "g2", "reddit"],
        "segment": "organiser_saas",
        "region": "US",
        "active": False,
        # Surfaced by G2's own search on 2026-08-02, so the slug is verified even
        # though the brand has never been scanned.
        "g2_slug": "cvent-event-marketing-management",
    },
    "vFairs": {
        "sources": ["tech", "g2", "reddit"],
        "segment": "organiser_saas",
        "region": "US",
        "active": False,
        "g2_slug": "vfairs",
    },
    "Whova": {
        "sources": ["tech", "g2", "reddit"],
        "segment": "organiser_saas",
        "region": "US",
        "active": False,
        "g2_slug": "whova",
    },
    "Zeffy": {
        "sources": ["tech", "g2", "reddit"],
        "segment": "organiser_saas",
        "region": "US",
        "active": False,
        "g2_slug": "zeffy",
    },
}

# Derived, so there is exactly one place to add a brand.
COMPETITORS: list[tuple[str, list[str]]] = [
    (name, brand["sources"]) for name, brand in BRANDS.items()
]

# Brands the scan should actually walk. `scan.run()` reads the watchlist rather
# than this, but seeding uses it to decide what to switch on.
ACTIVE_COMPETITORS = [n for n, b in BRANDS.items() if b.get("active")]


def segment_of(competitor: str) -> str | None:
    return (BRANDS.get(competitor) or {}).get("segment")

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

# The same categories in language a person would use out loud. The drafter needs
# these: a prompt handed `reporting_gaps` writes about "reporting gaps", which is
# our internal taxonomy leaking into someone's inbox. Phrased as the problem an
# organiser has, not as a product category.
COMPLAINT_LABELS: dict[str, str] = {
    "high_fees": "how much of each ticket the platform keeps",
    "payout_delay": "waiting weeks for the money after the event has finished",
    "refund_handling": "handling cancellations and refunds by hand",
    "checkin_problems": "scanning and door entry falling over at the gate",
    "poor_support": "nobody answering on the day of the event",
    "limited_customization": "not being able to make the booking page look like theirs",
    "integration_gaps": "the platform not talking to the tools they already run",
    "reporting_gaps": "not getting usable attendee data out afterwards",
    "reliability": "the platform going down when tickets go on sale",
}

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
    # Built in Phase C as free JSON-LD parsers, then **tested and blocked**
    # 2026-08-03. Both sites return 403 to their own robots.txt from this VM's
    # datacenter IP, which the collectors treat as a refusal to crawl. That is a
    # definitive answer, not a missing slug: no amount of slug verification opens
    # a door the site closed before we asked what was behind it.
    #
    # Reopening either needs an actor with residential proxies, i.e. money — which
    # puts them in the same category as Capterra rather than in the free tier they
    # were built for.
    "trustradius": {"audience": "organiser", "status": "blocked",
                    "note": "403 on robots.txt from this host (tested 2026-08-03). "
                            "Collector built and free; needs residential proxies"},
    "softwaresuggest": {"audience": "organiser", "status": "blocked",
                        "note": "403 on robots.txt from this host (tested "
                                "2026-08-03). Was the best free candidate for "
                                "Townscript/Explara/MeraEvents, which have no G2 "
                                "presence — that route is closed without proxies"},
    "product_hunt": {"audience": "organiser", "status": "untried",
                     "note": "Free official GraphQL API, but launch-era comments only — "
                             "thin for established platforms"},

    # ---- attendee-facing: high volume, wrong person ----
    # Moved out of "wrong-audience" on 2026-08-03: the audience turned out to be
    # a property of the brand rather than of the site. Built, and gated on
    # `segment` plus a hand-verified URL — see TRUSTPILOT_URLS below.
    "trustpilot": {"audience": "depends on brand segment", "status": "working",
                   "note": "consumer marketplaces yield ticket buyers; "
                           "organiser-facing SaaS yields organisers. $0.05/run, "
                           "verified slugs only"},
    "google_reviews": {"audience": "attendee", "status": "wrong-audience",
                       "note": "Local/consumer reviews; also needs the paid Places API"},
    "appsumo": {"audience": "organiser", "status": "wrong-audience",
                "note": "Only lists products that ran an AppSumo deal — none of "
                        "these did, so there is nothing to collect"},
}

# G2 product slugs, discovered via the scraper's search mode on 2026-08-02 and
# now derived from BRANDS so a slug is recorded beside the brand it belongs to.
# Guessing a slug returns "product not found" and a silent zero, so only
# verified entries carry one.
#
# Finding worth keeping: of the Indian watchlist, **only Eventbrite has a real
# G2 presence** (910 reviews). BookMyShow, Townscript, Explara and Paytm
# Insider returned nothing — G2 is a US/global B2B review site and India's
# ticketing platforms are not reviewed there. For those, G2 is not a usable
# signal source and the value has to come from tech detection, forums, job
# postings, and app-store reviews instead.
G2_SLUGS: dict[str, str] = {
    name.lower(): brand["g2_slug"]
    for name, brand in BRANDS.items() if brand.get("g2_slug")
}

# ------------------------------------------------------------- Trustpilot
#
# An allow-list of hand-checked business pages, keyed by lowercased brand. The
# collector looks a brand up here and returns nothing when it is absent. That is
# the whole design: Trustpilot's own search matches on name, and a name match
# once cost us twelve reviews about printer ink.
TRUSTPILOT_URLS: dict[str, str] = {
    name.lower(): brand["trustpilot_url"]
    for name, brand in BRANDS.items() if brand.get("trustpilot_url")
}

TRUSTPILOT_NOTES: dict[str, str] = {
    name.lower(): brand["trustpilot_note"]
    for name, brand in BRANDS.items() if brand.get("trustpilot_note")
}

# Slugs that look right and are not. Kept as data so the mistake cannot be made
# twice by someone who reasonably assumes a brand's domain is its slug.
TRUSTPILOT_REJECTED: dict[str, str] = {
    "tito": "ti.to resolves to Tito-Express, a German printer-ink retailer — "
            "twelve reviews about undelivered toner cartridges, zero about ticketing",
}

# Brands whose page is verified to exist but whose reviewers are the wrong
# people. Distinct from "unverified": we know, we paid to find out, and the
# answer was no. `collect()` refuses these before starting a run.
TRUSTPILOT_WRONG_AUDIENCE = ("eventbrite", "weezevent")

# ------------------------------------------- free B2B review sites (Phase C)
#
# TrustRadius and SoftwareSuggest publish schema.org Review JSON-LD, so they need
# no actor and no credit. SoftwareSuggest is the interesting one for this market:
# it is Indian, and Townscript, Explara and MeraEvents have no G2 footprint at all.
#
# **Empty by design.** Same allow-list rule as Trustpilot, for the same reason —
# a guessed slug either 404s or returns a different product's reviews, and the
# second outcome writes another company's complaints into our signal table under
# our competitor's name. Populate with:
#
#     python -m scripts.verify_review_slugs
#
# which fetches each candidate page and prints the product name it actually found,
# so the check is a diff rather than a memory. Free.
B2B_REVIEW_SLUGS: dict[str, dict[str, str]] = {
    "trustradius": {},
    "softwaresuggest": {},
}

# Candidate slugs to try, keyed by site then brand. These are guesses derived from
# each site's URL convention and are NOT verified — the script above exists to
# turn one into a B2B_REVIEW_SLUGS entry, and until it does the collectors refuse
# to fetch them.
B2B_SLUG_CANDIDATES: dict[str, dict[str, str]] = {
    "trustradius": {
        "eventbrite": "eventbrite",
        "ticketmaster": "ticketmaster",
        "cvent": "cvent",
        "whova": "whova",
        "vfairs": "vfairs",
        "zoho backstage": "zoho-backstage",
    },
    "softwaresuggest": {
        "townscript": "townscript",
        "explara": "explara",
        "meraevents": "meraevents",
        "zoho backstage": "zoho-backstage",
        "eventbrite": "eventbrite",
        "ticket tailor": "ticket-tailor",
    },
}

# Subreddits worth searching. The audience rule from REVIEW_SOURCES applies
# here too and is easy to get wrong: r/festivals and r/aves are full of ticket
# buyers venting about queues and refunds, which reads like rich signal and is
# the wrong person entirely. These are the organiser-side communities.
# Ordered by how concentrated the organiser audience is, because the collector
# walks them in order and a rate limit cuts the tail rather than the head.
SUBREDDITS = (
    # Professional organisers, where a platform complaint is on-topic
    "eventprofs",
    "eventplanning",
    "EventProduction",
    "festivalorganizers",
    "events",
    # Indian SME founders — the buyer, discussing tooling rather than events
    "IndiaBusiness",
    "StartUpIndia",
    # Broad, kept last: with `restrict_sr` and a vendor-name query these still
    # surface organisers, but they are the lowest-yield of the set.
    "Entrepreneur",
    "smallbusiness",
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
