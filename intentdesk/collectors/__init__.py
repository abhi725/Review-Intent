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

    def missing_credentials(self) -> list[str]:
        return [r for r in self.requires if not getattr(settings, r, "")]

    def available(self) -> bool:
        return not self.missing_credentials()

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
    from intentdesk.collectors.reddit import RedditCollector

    return [
        RedditCollector(),
        NotYetBuilt("builtwith", "install", ("builtwith_api_key",),
                    "install-base detection — CSV import covers this meanwhile"),
        NotYetBuilt("apify_g2", "review", ("apify_token",),
                    "G2 negative reviews via Apify actor"),
        NotYetBuilt("apify_capterra", "review", ("apify_token",),
                    "Capterra negative reviews via Apify actor"),
        NotYetBuilt("apify_jobs", "job_post", ("apify_token",),
                    "job postings naming the competitor"),
        NotYetBuilt("vendor_news", "vendor_news", (),
                    "price-hike announcements — needs a working feed URL, the "
                    "Zendesk blog feed 404s"),
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
            "note": getattr(c, "note", None),
        })
    return out
