"""Collectors turn the outside world into signals.

Every collector reports whether it is actually usable. That honesty matters:
the failure mode this system is most likely to hide is a source that silently
returns nothing, which looks identical to a quiet week. `availability()` makes
"not wired up yet" and "wired up but found nothing" impossible to confuse.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from intentdesk.config import settings


@dataclass
class RawSignal:
    kind: str
    source: str
    source_id: str
    observed_at: datetime
    quote: Optional[str] = None
    raw_text: Optional[str] = None
    company_name: Optional[str] = None
    company_domain: Optional[str] = None
    city: Optional[str] = None
    agents_est: Optional[int] = None
    vendor: Optional[str] = None
    # Provenance, for the feed. Every collector already has these to hand and
    # used to drop them — `rating` most conspicuously, which apify.py filtered
    # on and then discarded, leaving the UI able to say a review was negative
    # but not how negative.
    url: Optional[str] = None
    author: Optional[str] = None
    author_role: Optional[str] = None
    rating: Optional[float] = None
    # Everything below is returned by the live actors and was being dropped on
    # the floor. Checked against 50 G2 and 56 Trustpilot records, 2026-08-03.
    # `platform` is the product reviewed; `source_site` is where the review
    # lives. They differ: one collector can serve several sites, and the feed
    # groups by site rather than by the code that fetched it.
    platform: Optional[str] = None
    source_site: Optional[str] = None
    country: Optional[str] = None
    region: Optional[str] = None
    # A reviewer saying outright that they changed platforms, and why. The
    # strongest buying signal in the payload.
    switched_from: Optional[str] = None
    switched_reason: Optional[str] = None
    # Per-dimension scores where the source publishes them (G2 does, Trustpilot
    # does not). A dict rather than fields, because the dimensions differ by
    # source and a fixed set would force every source to fake the others.
    subscores: Optional[dict] = None


class Collector:
    name: str = "base"
    kind: str = "install"
    requires: tuple[str, ...] = ()

    # "scheduled" collectors are free and safe to run on a cron. "on_demand"
    # ones cost money and must be triggered deliberately, with the price shown
    # before the click. The scheduled scan filters on this: paid work running
    # unattended is the spending pattern this design exists to prevent.
    cadence: str = "on_demand"
    cost_model: str = "per_run"      # free | per_run | per_item

    # False excludes a collector from ever running. Set when a site's
    # robots.txt disallows the path, or refuses to serve robots.txt at all.
    robots_ok: bool = True

    # Set when a collector is credential-ready but known not to work, so status
    # never reports READY for something that fails on every run. Capterra is the
    # case this exists for: the token is valid, the source blocks the scrape.
    known_broken: str = ""

    def missing_credentials(self) -> list[str]:
        return [r for r in self.requires if not getattr(settings, r, "")]

    def available(self) -> bool:
        return not self.missing_credentials() and not self.known_broken

    async def collect(self, competitor: str) -> list[RawSignal]:
        raise NotImplementedError


class NotYetBuilt(Collector):
    """Declared but unimplemented. Present so the dashboard can show what the
    pipeline is still missing rather than quietly omitting it."""

    def __init__(self, name: str, kind: str, requires: tuple[str, ...], note: str):
        self.name = name
        self.kind = kind
        self.requires = requires
        self.note = note

    def available(self) -> bool:
        return False

    async def collect(self, competitor: str) -> list[RawSignal]:
        raise NotImplementedError(f"{self.name}: {self.note}")


def registry() -> list[Collector]:
    from intentdesk.collectors.apify import CapterraReviewCollector, G2ReviewCollector
    from intentdesk.collectors.jobs import JobPostCollector
    from intentdesk.collectors.news import VendorNewsCollector
    from intentdesk.collectors.reddit import RedditCollector
    from intentdesk.collectors.reviews_b2b import (
        SoftwareSuggestCollector,
        TrustRadiusCollector,
    )
    from intentdesk.collectors.trustpilot import TrustpilotReviewCollector

    # Ordered cheapest-first so that when the spend cap stops the run, what got
    # skipped is the expensive tail rather than an arbitrary slice.
    return [
        VendorNewsCollector(),          # free
        SoftwareSuggestCollector(),     # free, unverified — Indian B2B reviews
        TrustRadiusCollector(),         # free, unverified
        RedditCollector(),              # free, needs an OAuth app
        TrustpilotReviewCollector(),    # $0.05 per run of up to 20 reviews
        JobPostCollector(),             # ~$0.006 per listing
        G2ReviewCollector(),            # ~$0.06 per review
        CapterraReviewCollector(),
    ]


def get(name: str) -> Optional[Collector]:
    """One collector by name, for the per-source trigger.

    A fresh instance each call rather than a shared one: collectors carry
    `last_cost_usd` and `last_skip_reason` from their most recent run, and two
    concurrent triggers reading each other's cost is a billing figure that is
    wrong in a way nobody would think to check.
    """
    for coll in registry():
        if coll.name == name:
            return coll
    return None


# Sources deliberately not in the registry, and why. Kept as data so the
# dashboard can say "decided against" rather than leaving a gap that looks like
# an oversight and gets rebuilt by the next person.
RETIRED: list[dict] = [
    {"name": "builtwith", "reason": "superseded — Apollo's organizations/enrich "
                                    "returns technology_names, which detects the "
                                    "ticketing platform without a subscription"},
    # Trustpilot was here and has been **built** — see collectors/trustpilot.py.
    # The original reason was right about Eventbrite (20/20 negative reviews were
    # ticket buyers) and wrong as a general rule: on organiser-facing brands the
    # audience flips. It now runs against a hand-verified allow-list, gated on
    # `market.BRANDS[...]["segment"]`, so the finding is enforced per brand
    # instead of retiring the whole source.
    #
    # `ti.to` name-matched Tito-Express, a German printer-ink retailer, and
    # returned twelve reviews about undelivered toner cartridges.
    {"name": "gmb_reviews", "reason": "Google My Business reviews are about the "
                                      "office, not the product — BookMyShow's "
                                      "listing is reception complaints. GMB is "
                                      "used for enrichment instead."},
    {"name": "linkedin_jobs", "reason": "only flat-rate actors ($25–39/month), which "
                                        "does not fit a $5 Apify account"},
]


# What a source's rows cost, by collector name. Kept here rather than on each
# class so the Sources panel can price a control without instantiating anything,
# and so the price and the action name stay in one table — see services/spend.py.
PRICED_ACTION: dict[str, str] = {
    "vendor_news": "collect_news",
    "reddit": "collect_reddit",
    "trustpilot": "collect_trustpilot",
    "apify_g2": "collect_g2",
    "trustradius": "collect_b2b_reviews",
    "softwaresuggest": "collect_b2b_reviews",
}


def availability() -> list[dict]:
    from intentdesk.services import spend

    out = []
    for c in registry():
        action = PRICED_ACTION.get(c.name)
        # `units=1` is a per-unit price, not a run total — the caller multiplies
        # by whatever the row cap is set to. A run total here would understate
        # every per-item source by the size of its batch.
        price = spend.estimate(action, 1) if action else None

        out.append({
            "name": c.name,
            "kind": c.kind,
            "available": c.available(),
            "missing": c.missing_credentials(),
            "implemented": not isinstance(c, NotYetBuilt),
            "note": getattr(c, "note", None) or c.known_broken or None,
            "known_broken": c.known_broken or None,
            "cadence": getattr(c, "cadence", "on_demand"),
            "cost_model": getattr(c, "cost_model", "per_run"),
            "action": action,
            "price": price,
            # Sources that refuse per brand rather than wholesale. The UI needs
            # this to decide whether to ask the backend about each competitor
            # before enabling a button.
            "gated_per_competitor": hasattr(c, "check"),
        })

    # Discovery sources are not signal collectors — they find companies rather
    # than evidence — but the dashboard should still show them, because "no
    # leads" and "no discovery running" are different problems with different
    # fixes.
    from intentdesk.collectors.organisers import DISCOVERY

    for cls in DISCOVERY:
        out.append({
            "name": cls.name,
            "kind": "discovery",
            "available": True,
            "missing": [],
            "implemented": True,
            "note": f"free — public sitemap, finds companies running {cls.platform}",
            "known_broken": None,
            "cadence": cls.cadence,
            "cost_model": cls.cost_model,
            "action": "discover_organisers",
            "price": spend.estimate("discover_organisers", 1),
            "gated_per_competitor": False,
        })
    return out
