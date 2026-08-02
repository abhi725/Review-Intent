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


class Collector:
    name: str = "base"
    kind: str = "install"
    requires: tuple[str, ...] = ()

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

    # Ordered cheapest-first so that when the spend cap stops the run, what got
    # skipped is the expensive tail rather than an arbitrary slice.
    return [
        VendorNewsCollector(),   # free
        RedditCollector(),       # free, needs an OAuth app
        JobPostCollector(),      # ~$0.006 per listing
        G2ReviewCollector(),     # ~$0.06 per review
        CapterraReviewCollector(),
    ]


# Sources deliberately not in the registry, and why. Kept as data so the
# dashboard can say "decided against" rather than leaving a gap that looks like
# an oversight and gets rebuilt by the next person.
RETIRED: list[dict] = [
    {"name": "builtwith", "reason": "superseded — Apollo's organizations/enrich "
                                    "returns technology_names, which detects the "
                                    "ticketing platform without a subscription"},
    {"name": "trustpilot", "reason": "wrong audience — reviewers are ticket buyers, "
                                     "not the organisers who buy the platform"},
    {"name": "linkedin_jobs", "reason": "only flat-rate actors ($25–39/month), which "
                                        "does not fit a $5 Apify account"},
]


def availability() -> list[dict]:
    out = []
    for c in registry():
        out.append({
            "name": c.name,
            "kind": c.kind,
            "available": c.available(),
            "missing": c.missing_credentials(),
            "implemented": not isinstance(c, NotYetBuilt),
            "note": getattr(c, "note", None) or c.known_broken or None,
            "known_broken": c.known_broken or None,
        })
    return out
