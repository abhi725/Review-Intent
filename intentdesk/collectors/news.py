"""Vendor news — price rises, outages, breaches.

Google News RSS rather than vendor blog feeds. The original plan pointed at the
vendors' own feeds, which 404 — and even when they resolve, a vendor's blog is
the last place a price rise gets described as one. Google News needs no key, no
Apify credit and no account, which makes this the only collector that costs
nothing to run.

What this produces is *timing*, not leads. A news item names the vendor, never
their customers, so these signals land unmatched by design and act as a
multiplier on companies already in the install base: a price hike is the week
their renewal conversation gets easier.

Scoring already reflects that — `vendor_news` is the lowest-weighted kind at 15.
"""

import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import quote_plus

import httpx

from intentdesk.collectors import Collector, RawSignal
from intentdesk.market import NEWS_RSS, NEWS_TRIGGER_TERMS

RECENCY_DAYS = 90
_TAGS = re.compile(r"<[^>]+>")


def _clean(text: str | None) -> str:
    """RSS descriptions arrive as HTML fragments."""
    return _TAGS.sub(" ", text or "").replace("&nbsp;", " ").strip()


def _published(entry: ET.Element) -> datetime:
    raw = (entry.findtext("pubDate") or "").strip()
    if raw:
        try:
            when = parsedate_to_datetime(raw)
            return when if when.tzinfo else when.replace(tzinfo=timezone.utc)
        except (TypeError, ValueError):
            pass
    return datetime.now(timezone.utc)


class VendorNewsCollector(Collector):
    name = "vendor_news"
    kind = "vendor_news"
    requires = ()  # free: no key, no account

    def __init__(self, max_items: int = 25):
        self.max_items = max_items
        self.last_cost_usd = 0.0

    async def collect(self, competitor: str) -> list[RawSignal]:
        # A bare vendor name returns event listings and funding gossip. Pairing
        # it with the trigger words is what makes this a churn signal instead of
        # a press-release feed.
        triggers = " OR ".join(f'"{t}"' for t in ("price increase", "fees", "outage",
                                                  "data breach", "layoffs", "shuts down"))
        query = f'"{competitor}" ({triggers})'
        url = NEWS_RSS.format(query=quote_plus(query))

        async with httpx.AsyncClient(timeout=25, follow_redirects=True) as client:
            response = await client.get(url, headers={"User-Agent": "swan-intent-desk/0.1"})
            response.raise_for_status()

        try:
            root = ET.fromstring(response.content)
        except ET.ParseError as exc:
            raise RuntimeError(f"google news returned unparseable XML: {exc}") from exc

        cutoff = datetime.now(timezone.utc) - timedelta(days=RECENCY_DAYS)
        out: list[RawSignal] = []

        for entry in list(root.iterfind(".//item"))[: self.max_items]:
            title = _clean(entry.findtext("title"))
            summary = _clean(entry.findtext("description"))
            haystack = f"{title} {summary}".lower()

            # Google's OR query is fuzzy enough to return items matching neither
            # the vendor nor a trigger. Both are re-checked here.
            if competitor.lower() not in haystack:
                continue
            if not any(term in haystack for term in NEWS_TRIGGER_TERMS):
                continue

            when = _published(entry)
            if when < cutoff:
                continue

            link = (entry.findtext("link") or "").strip()
            guid = (entry.findtext("guid") or link or title).strip()

            out.append(
                RawSignal(
                    kind="vendor_news",
                    source="google_news",
                    source_id=f"gnews:{guid[:200]}",
                    observed_at=when,
                    quote=title[:280],
                    raw_text=f"{title}\n\n{summary}\n\n{link}"[:4000],
                    vendor=competitor,
                    # News is about the vendor, never about one of its
                    # customers, so this stays unmatched on purpose.
                    company_name=None,
                    company_domain=None,
                )
            )

        return out
