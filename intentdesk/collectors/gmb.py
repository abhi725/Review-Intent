"""Google My Business lookup, via `compass~crawler-google-places`.

**Enrichment only. This is not a review source.** Tested 2026-08-03: the
listing for "BookMyShow Office, Mumbai" has 133 reviews at 4.1, but they are
about the office — `1★ "Would not even pick up the call"` — not the ticketing
product. And a search for "Eventbrite office" returned **The Event Group**, an
unrelated Denver event planner. Mining GMB for platform complaints would fill
the queue with reception reviews and mismatched brands.

As an enrichment source it outranks Apollo for this market, on two measured
points:

  "9 Blocks Photography Hyderabad" -> https://www.9blocks.in/  +91 98490 46439
  "4moles Golf"                    -> http://www.4moles.com/   +91 99582 65656

  1. It returns a PHONE NUMBER. Apollo returned `phone: None` for the same
     company. Outreach here is phone-first by default, so the field that
     decides whether a lead is contactable at all comes from Google.
  2. It returns the WEBSITE, which is precisely the input Apollo's
     organizations/enrich needs. GMB can replace the name->domain step.

Measured cost: $0.0082 for 3 lookups, ~$0.0027 each.
"""

import asyncio
import logging
import re
from typing import Optional
from urllib.parse import urlparse

import httpx

from intentdesk.config import settings

log = logging.getLogger(__name__)

API = "https://api.apify.com/v2"
ACTOR = "compass~crawler-google-places"

# Categories that mean the search landed on something that is not the business
# we asked for. A ticketing organiser is not a hotel chain or an airport.
WRONG_KIND = re.compile(
    r"\b(airport|railway station|bus station|atm|petrol|gas station|"
    r"post office|police|hospital|pharmacy)\b",
    re.I,
)


def domain_of(url: Optional[str]) -> Optional[str]:
    if not url:
        return None
    host = (urlparse(url).netloc or "").lower()
    host = host.split(":")[0]
    if host.startswith("www."):
        host = host[4:]
    # A link to a social profile is not the company's own domain, and treating
    # it as one would key several unrelated companies to the same row.
    if not host or host.count(".") < 1:
        return None
    if any(host.endswith(bad) for bad in (
        "facebook.com", "instagram.com", "linkedin.com", "twitter.com",
        "x.com", "youtube.com", "wa.me", "bit.ly", "linktr.ee",
        "meraevents.com", "townscript.com", "eventbrite.com", "bookmyshow.com",
    )):
        return None
    return host


class GmbLookup:
    name = "gmb"
    cadence = "on_demand"
    cost_model = "per_item"
    unit_cost_usd = 0.0027   # measured, not quoted
    requires = ("apify_token",)

    def __init__(self, timeout_s: int = 420):
        self.timeout_s = timeout_s
        self.last_cost_usd = 0.0

    async def lookup(self, queries: list[str]) -> tuple[list[dict], float]:
        """One actor run for many names. Batched because the actor charges per
        place, not per run, so a run per name multiplies startup overhead for
        nothing."""
        if not settings.apify_token:
            raise RuntimeError("APIFY_TOKEN is not set")
        if not queries:
            return [], 0.0

        payload = {
            "searchStringsArray": queries,
            "maxCrawledPlacesPerSearch": 1,
            "language": "en",
            # Reviews are explicitly not wanted: see the module docstring. They
            # would also be charged for.
            "maxReviews": 0,
        }
        headers = {"Authorization": f"Bearer {settings.apify_token}"}

        async with httpx.AsyncClient(timeout=90) as client:
            start = await client.post(f"{API}/acts/{ACTOR}/runs",
                                      headers=headers, json=payload)
            start.raise_for_status()
            run = start.json()["data"]
            run_id, dataset_id = run["id"], run["defaultDatasetId"]

            waited, status = 0, run["status"]
            while status in ("READY", "RUNNING") and waited < self.timeout_s:
                await asyncio.sleep(6)
                waited += 6
                poll = await client.get(f"{API}/actor-runs/{run_id}", headers=headers)
                poll.raise_for_status()
                status = poll.json()["data"]["status"]

            detail = (await client.get(f"{API}/actor-runs/{run_id}",
                                       headers=headers)).json()["data"]
            cost = float(detail.get("usageTotalUsd") or 0)
            self.last_cost_usd = cost

            if status != "SUCCEEDED":
                raise RuntimeError(f"{ACTOR} finished as {status} after {waited}s")

            items = await client.get(f"{API}/datasets/{dataset_id}/items",
                                     headers=headers, params={"limit": 1000})
            items.raise_for_status()
            return items.json(), cost

    @staticmethod
    def parse(item: dict) -> dict:
        """Normalise one place into the fields the resolver cares about."""
        return {
            "matched_name": item.get("title"),
            "domain": domain_of(item.get("website")),
            "phone": (item.get("phone") or "").strip() or None,
            "address": item.get("address"),
            "city": item.get("city"),
            "country_code": item.get("countryCode"),
            "category": item.get("categoryName"),
            "rating": item.get("totalScore"),
            "wrong_kind": bool(WRONG_KIND.search(item.get("categoryName") or "")),
        }
