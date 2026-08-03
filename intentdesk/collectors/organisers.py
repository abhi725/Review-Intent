"""Organiser discovery from public sitemaps — the free route into `companies`.

This is the collector the whole pipeline was missing. Reviews cannot fill the
company table: 25 G2 reviews yield 25 pseudonyms and zero domains. But every
event platform publishes, for crawlers, a list of the organisers using it — and
an organiser on MeraEvents' sitemap is by definition a company running
MeraEvents. That is exactly the install-base fact BuiltWith charges ~$295/month
to infer.

Verified 2026-08-03, $0 spent:
    meraevents.com/sitemaps/organizers/1  -> 7,273 organiser profiles
    townscript.com/sitemap/upcoming-event-pages.xml -> 7,547 events
    townscript.com/sitemap/past-event-pages.xml     -> 40,000 events

robots.txt is checked, not assumed. Both of these publish zero disallow rules
for `*`. Explara disallows `/e/` and is therefore not here; BookMyShow and
AllEvents return 403 to their own robots.txt and are not here either.

These collectors do not emit RawSignal. A discovered organiser is not evidence
of intent — it is a company that exists. It goes to the `organisers` staging
table, and only a confidently resolved domain is promoted to `companies`.
"""

import asyncio
import json
import logging
import re
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlparse

import httpx

from intentdesk import db

log = logging.getLogger(__name__)

UA = "swan-intent-desk/0.5 (+https://intent.swandigitals.com)"
TIMEOUT = 30.0

# Polite crawling. These are public files served to search engines, but a
# sitemap with 40,000 entries is not an invitation to fetch it at full speed.
CONCURRENCY = 4
DELAY_S = 0.25


@dataclass
class Organiser:
    name: str
    platform: str
    source: str
    profile_url: Optional[str] = None
    city: Optional[str] = None


def _locs(body: bytes) -> list[str]:
    return [m.decode() for m in re.findall(rb"<loc>\s*([^<\s]+)\s*</loc>", body)]


async def robots_allows(client: httpx.AsyncClient, base: str, path: str) -> bool:
    """Refuse to crawl what a site has asked crawlers not to.

    Enforced in code rather than left to whoever writes the next collector.
    A 403 on robots.txt itself is treated as a refusal: BookMyShow and AllEvents
    both do this, and reading past it would be helping ourselves to something
    the site declined to describe.
    """
    try:
        r = await client.get(f"{base}/robots.txt")
    except httpx.HTTPError as exc:
        log.warning("robots.txt unreachable for %s (%s) — refusing to crawl", base, exc)
        return False
    if r.status_code != 200:
        log.warning("robots.txt for %s returned %s — refusing to crawl", base, r.status_code)
        return False

    agent = None
    for line in r.text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, _, value = line.partition(":")
        key, value = key.strip().lower(), value.strip()
        if key == "user-agent":
            agent = value
        elif key == "disallow" and agent == "*" and value:
            # Prefix match is what the standard specifies.
            if path.startswith(value.rstrip("*")):
                log.warning("robots.txt disallows %s%s", base, path)
                return False
    return True


class MeraEventsOrganisers:
    """MeraEvents publishes an organiser sitemap. 7,273 named companies, free.

    This is the single highest-yield free source in the project: every entry is
    a company demonstrably using a tracked competitor, with a name good enough
    to resolve into a domain.
    """

    name = "meraevents_organisers"
    kind = "install"
    cadence = "scheduled"
    cost_model = "free"
    platform = "MeraEvents"
    base = "https://meraevents.com"
    sitemap_path = "/sitemaps/organizers/1"

    # A profile slug carries the name, but truncated and hyphenated with a
    # random suffix ("aace-india-mbldg"). The page <title> has the real one.
    TITLE = re.compile(r"<title>(.*?)</title>", re.S | re.I)
    SUFFIX = re.compile(
        r"\s*(?:&#x27;s|'s)?\s*(?:organization\s*)?Events?\s*&(?:amp;)?\s*Tickets?"
        r"\s*\|\s*MeraEvents\s*$",
        re.I,
    )

    def __init__(self, limit: int = 500):
        # Deliberately capped. The full 7,273 is a deliberate, resumable run,
        # not something a scheduled scan should attempt in one pass.
        self.limit = limit
        self.last_cost_usd = 0.0

    def _clean(self, title: str) -> str:
        name = self.SUFFIX.sub("", title.strip())
        name = (name.replace("&amp;", "&").replace("&#x27;", "'")
                    .replace("&quot;", '"').replace("&#39;", "'"))
        return re.sub(r"\s+", " ", name).strip()

    async def collect(self) -> list[Organiser]:
        async with httpx.AsyncClient(
            headers={"User-Agent": UA}, timeout=TIMEOUT, follow_redirects=True
        ) as client:
            if not await robots_allows(client, self.base, self.sitemap_path):
                return []

            r = await client.get(f"{self.base}{self.sitemap_path}")
            r.raise_for_status()
            urls = _locs(r.content)
            log.info("%s: %d organiser profiles in sitemap", self.name, len(urls))

            # Skip profiles already stored, so a repeat run costs only the new
            # ones instead of re-fetching seven thousand pages.
            known = {
                row["profile_url"]
                for row in await db.fetch(
                    "SELECT profile_url FROM organisers WHERE source = $1", self.name
                )
                if row["profile_url"]
            }
            todo = [u for u in urls if u not in known][: self.limit]
            log.info("%s: %d new, %d already known", self.name, len(todo), len(known))

            sem = asyncio.Semaphore(CONCURRENCY)

            async def one(url: str) -> Optional[Organiser]:
                async with sem:
                    await asyncio.sleep(DELAY_S)
                    try:
                        page = await client.get(url)
                    except httpx.HTTPError:
                        return None
                    if page.status_code != 200:
                        return None
                    m = self.TITLE.search(page.text)
                    if not m:
                        return None
                    name = self._clean(m.group(1))
                    # A slug-derived stub or an empty title is not a company.
                    if len(name) < 2:
                        return None
                    return Organiser(
                        name=name,
                        platform=self.platform,
                        source=self.name,
                        profile_url=url,
                    )

            results = await asyncio.gather(*(one(u) for u in todo))
            return [o for o in results if o]


class TownscriptOrganisers:
    """Townscript event pages — **closed for free, diagnosed 2026-08-03.**

    This returned 0 and the first explanation was wrong in a way that would have
    cost real effort: the sitemap does carry pharmacy spam ("best website to shop
    lorazepam without prescription"), so the obvious next step was a better spam
    filter. That would have found nothing.

    The actual reason, measured across 16 pages sampled from both sitemaps: every
    Townscript event page is a **client-rendered shell**. `/e/<slug>` returns
    ~5.6 KB whose only JSON-LD is a site-level `WebSite` node — no `Event`, no
    `performer`, no organiser, no event data at all. Same as Paytm Insider. The
    original note said the field was "present on roughly half the pages sampled";
    re-checked, it is present on none.

    Both sitemaps are real and large (7,551 upcoming, 40,000 past) and the past
    one is mostly genuine Indian events rather than spam, so the *addresses* are
    there. What is missing is anything to read at them, which needs a headless
    browser rather than a better regex.

    Kept registered and returning [] rather than deleted: the sitemap parsing and
    robots handling are correct, and "we looked and the pages are empty" is worth
    more on the Sources panel than a gap where a collector used to be.
    """

    name = "townscript_organisers"
    kind = "install"
    cadence = "scheduled"
    cost_model = "free"
    platform = "Townscript"
    base = "https://www.townscript.com"
    sitemap_path = "/sitemap/upcoming-event-pages.xml"

    # Pharmacy spam is the dominant junk pattern on this sitemap.
    SPAM = re.compile(
        r"\b(lorazepam|alprazolam|xanax|tramadol|adderall|ambien|oxycodone|"
        r"valium|klonopin|percocet|vicodin|without\s+prescription|"
        r"buy\s+\w+\s+online\s+overnight)\b",
        re.I,
    )

    def __init__(self, limit: int = 300):
        self.limit = limit
        self.last_cost_usd = 0.0

    def _organiser_of(self, html: str) -> Optional[str]:
        for block in re.findall(
            r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>', html, re.S | re.I
        ):
            try:
                data = json.loads(block.strip())
            except (json.JSONDecodeError, ValueError):
                continue
            stack = data if isinstance(data, list) else [data]
            while stack:
                node = stack.pop()
                if isinstance(node, list):
                    stack.extend(node)
                    continue
                if not isinstance(node, dict):
                    continue
                if "@graph" in node:
                    stack.extend(node["@graph"])
                for key in ("organizer", "performer"):
                    value = node.get(key)
                    if isinstance(value, dict) and value.get("name"):
                        return str(value["name"])
                    if isinstance(value, str) and value.strip():
                        return value.strip()
        return None

    async def collect(self) -> list[Organiser]:
        async with httpx.AsyncClient(
            headers={"User-Agent": UA}, timeout=TIMEOUT, follow_redirects=True
        ) as client:
            if not await robots_allows(client, self.base, self.sitemap_path):
                return []

            r = await client.get(f"{self.base}{self.sitemap_path}")
            r.raise_for_status()
            urls = [u for u in _locs(r.content) if not self.SPAM.search(u)]
            log.info("%s: %d event pages after spam filter", self.name, len(urls))

            known = {
                row["profile_url"]
                for row in await db.fetch(
                    "SELECT profile_url FROM organisers WHERE source = $1", self.name
                )
                if row["profile_url"]
            }
            todo = [u for u in urls if u not in known][: self.limit]

            sem = asyncio.Semaphore(CONCURRENCY)

            async def one(url: str) -> Optional[Organiser]:
                async with sem:
                    await asyncio.sleep(DELAY_S)
                    try:
                        page = await client.get(url)
                    except httpx.HTTPError:
                        return None
                    if page.status_code != 200:
                        return None
                    name = self._organiser_of(page.text)
                    if not name or len(name) < 2 or self.SPAM.search(name):
                        return None
                    return Organiser(
                        name=re.sub(r"\s+", " ", name).strip(),
                        platform=self.platform,
                        source=self.name,
                        profile_url=url,
                    )

            results = await asyncio.gather(*(one(u) for u in todo))

            # One organiser runs many events, so the same name arrives many
            # times. Dedup here rather than leaning on the unique constraint,
            # which would count every duplicate as a discovery.
            seen, out = set(), []
            for o in results:
                if o and o.name.lower() not in seen:
                    seen.add(o.name.lower())
                    out.append(o)
            return out


DISCOVERY = (MeraEventsOrganisers, TownscriptOrganisers)


async def store(organisers: list[Organiser]) -> dict:
    """Write discoveries to the staging table. Idempotent."""
    new = 0
    for o in organisers:
        row = await db.fetchrow(
            """
            INSERT INTO organisers (name, platform, source, profile_url, city)
            VALUES ($1,$2,$3,$4,$5)
            ON CONFLICT (source, name, platform) DO NOTHING
            RETURNING id
            """,
            o.name, o.platform, o.source, o.profile_url, o.city,
        )
        if row:
            new += 1
    return {"seen": len(organisers), "new": new}


async def discover(limit: int = 500) -> dict:
    """Run every discovery source. Free, so this is safe on a schedule."""
    totals = {"seen": 0, "new": 0, "by_source": {}}
    for cls in DISCOVERY:
        coll = cls(limit=limit)
        try:
            found = await coll.collect()
        except (httpx.HTTPError, ValueError) as exc:
            # One source failing must not stop the other. A collector that
            # returns nothing looks identical to a quiet week, so it is logged.
            log.warning("%s failed: %s", coll.name, exc)
            totals["by_source"][coll.name] = {"error": str(exc)[:200]}
            continue
        result = await store(found)
        totals["by_source"][coll.name] = result
        totals["seen"] += result["seen"]
        totals["new"] += result["new"]
    return totals
