"""TrustRadius and SoftwareSuggest — B2B review sources, via residential proxy.

Why these two and not more of Gartner's estate: GetApp, Capterra and Software
Advice share one data pool and one blocking policy, and Capterra already returns
403 to a paid actor from this box. TrustRadius is independently operated, and
**SoftwareSuggest is Indian** — which matters more than its size, because the
Indian ticketing platforms with no G2 footprint at all (Townscript, Explara,
MeraEvents) are exactly the brands an Indian review site would carry.

Both publish `schema.org/Review` as JSON-LD for their own SEO, which is why this
needs no scraping actor. It parses the structured data these pages already hand
to crawlers.

What it does need is a **residential exit**. Both sites answer this VM's
datacenter IP with 403 — on robots.txt itself — so the free direct route is
closed and the fetch goes through the Apify residential proxy instead. That
bandwidth is billed, which is why these are `on_demand` and `per_run` rather
than the free scheduled sources they were written as. See `proxy.py`.

Two things are enforced rather than assumed, both matching the pattern the rest of
this package uses:

* **robots.txt is checked** before any product page is fetched, via the same
  `robots_allows` the sitemap collectors use. A 403 on robots.txt is a refusal.
* **Slugs are an allow-list, never a search.** `market.B2B_REVIEW_SLUGS` starts
  empty on purpose. A name search on a review site once matched Tito-Express, a
  German printer-ink retailer, and billed us for twelve reviews about toner. The
  same mistake is free here and still wrong: it would write another vendor's
  complaints into our signal table under our competitor's name.

**Status: unverified.** These are written against the documented JSON-LD shape
and have never returned a row on this box, because there is no verified slug to
try and the datacenter IP is 403'd by several review sites already. `verified` is
False and `availability()` says so, so nothing reports READY for a source that has
never worked. `scripts/verify_review_slugs.py` is the free way to change that.
"""

import asyncio
import hashlib
import json
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx

from intentdesk.collectors import Collector, RawSignal
from intentdesk.collectors import proxy
from intentdesk.collectors.organisers import UA, robots_allows
from intentdesk.market import B2B_REVIEW_SLUGS

log = logging.getLogger(__name__)

TIMEOUT = 30.0
NEGATIVE_AT_OR_BELOW = 3
RECENCY_DAYS = 365

# Polite: these are product pages, not a bulk feed.
DELAY_S = 0.5


def json_ld_blocks(html: str) -> list[dict]:
    """Every JSON-LD object on the page, flattened.

    `@graph` is unwrapped and arrays are expanded, because both sites nest their
    review list differently and a parser that only handles one shape silently
    returns nothing on the other — the failure mode that looks like "no reviews".
    """
    out: list[dict] = []
    for match in re.finditer(
        r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        html, re.DOTALL | re.IGNORECASE,
    ):
        try:
            parsed = json.loads(match.group(1).strip())
        except (json.JSONDecodeError, ValueError):
            continue
        stack = [parsed]
        while stack:
            node = stack.pop()
            if isinstance(node, list):
                stack.extend(node)
            elif isinstance(node, dict):
                out.append(node)
                if "@graph" in node:
                    stack.append(node["@graph"])
    return out


def reviews_from_json_ld(html: str) -> list[dict]:
    """Pull `Review` nodes out, wherever they are nested.

    Reviews appear either as their own top-level nodes or inside a `Product`'s
    `review` array, and which one you get depends on the page template rather
    than on the site.
    """
    found: list[dict] = []
    for node in json_ld_blocks(html):
        node_type = node.get("@type")
        types = node_type if isinstance(node_type, list) else [node_type]
        if "Review" in types:
            found.append(node)
        nested = node.get("review") or node.get("reviews")
        if isinstance(nested, list):
            found.extend(n for n in nested if isinstance(n, dict))
        elif isinstance(nested, dict):
            found.append(nested)
    return found


def _rating(review: dict) -> Optional[float]:
    rating = review.get("reviewRating") or review.get("ratingValue")
    if isinstance(rating, dict):
        value, best = rating.get("ratingValue"), rating.get("bestRating")
    else:
        value, best = rating, None
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    # SoftwareSuggest rates out of 5; some templates publish out of 10. Without
    # this, a 6/10 — a poor score — reads as better than five stars and is
    # filtered out as a happy customer.
    try:
        best = float(best) if best is not None else 5.0
    except (TypeError, ValueError):
        best = 5.0
    if best and best != 5.0:
        value = value * 5.0 / best
    return round(value, 2)


def _author(review: dict) -> tuple[Optional[str], Optional[str]]:
    author = review.get("author")
    if isinstance(author, dict):
        return author.get("name"), author.get("jobTitle")
    if isinstance(author, str):
        return author, None
    return None, None


def _when(review: dict) -> Optional[datetime]:
    raw = review.get("datePublished") or review.get("dateCreated")
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


class _JsonLdReviewCollector(Collector):
    """Shared machinery. Subclasses supply the site's base URL and path shape."""

    kind = "review"
    requires = ()

    # Both sites 403 this VM's datacenter IP, so the only route that works is the
    # residential proxy — and residential bandwidth is billed. That makes these
    # paid, on-demand sources: there is no longer a free route to run on a cron,
    # and a paid source on a schedule is the spending pattern this design exists
    # to prevent. Declared as constants rather than switching with the proxy flag,
    # because a source whose cadence changes with configuration is one that could
    # quietly land back on the free scan.
    cadence = "on_demand"
    cost_model = "per_run"

    # Never returned a row on this box. Reported rather than hidden: a source
    # claiming READY when it has never worked is the failure this package's
    # `availability()` exists to prevent.
    verified = False

    @property
    def known_broken(self):
        """Blocked while there is no residential proxy, and only then.

        Tested 2026-08-03: both sites 403 their own robots.txt from this VM, and
        `robots_allows()` treats that as a refusal — reading past it would be
        helping ourselves to something the site declined to describe. That is a
        datacenter-IP 403, not a policy against us, so a residential exit is the
        fix. The parsing is correct against the documented JSON-LD shape, which is
        why this was kept rather than deleted.
        """
        if proxy.enabled():
            return None
        return f"403 on robots.txt from this host's datacenter IP — {proxy.NEEDS_PROXY}"

    base: str = ""
    site: str = ""
    path_template: str = ""
    country_default: Optional[str] = None

    def __init__(self, max_reviews: int = 50):
        self.max_reviews = max_reviews
        self.last_skip_reason: Optional[str] = None

    @property
    def note(self) -> str:
        slugs = B2B_REVIEW_SLUGS.get(self.site, {})
        if not slugs:
            return (f"free, but no hand-verified {self.site} slug exists yet — run "
                    f"scripts/verify_review_slugs.py. Never name-searched: a name "
                    f"match once returned another company's reviews entirely.")
        return (f"free JSON-LD parse; {len(slugs)} verified slug(s). "
                f"Unverified end to end — no live row returned from this box yet.")

    def available(self) -> bool:
        """False while no slug has been verified.

        A source with nothing it is allowed to fetch is not "ready" — it would
        run, return zero, and be indistinguishable from a week with no
        complaints. Saying so here is what keeps the Sources panel honest.
        """
        return bool(B2B_REVIEW_SLUGS.get(self.site)) and not self.known_broken

    def check(self, competitor: str) -> Optional[str]:
        slug = B2B_REVIEW_SLUGS.get(self.site, {}).get(competitor.strip().lower())
        if not slug:
            return (f"No hand-verified {self.site} slug for {competitor}. Verify one "
                    f"with scripts/verify_review_slugs.py and add it to "
                    f"market.B2B_REVIEW_SLUGS — a guessed slug either 404s or, "
                    f"worse, returns a different product's reviews.")
        return None

    async def collect(self, competitor: str) -> list[RawSignal]:
        reason = self.check(competitor)
        if reason:
            self.last_skip_reason = reason
            log.info("%s: skipping %s — %s", self.site, competitor, reason)
            return []
        self.last_skip_reason = None

        slug = B2B_REVIEW_SLUGS[self.site][competitor.strip().lower()]
        path = self.path_template.format(slug=slug)

        # The proxy is the whole reason this can run at all, so its absence is an
        # error rather than a fall-back to the direct route that is known to 403.
        proxy_url = proxy.url()
        if proxy_url is None:
            raise RuntimeError(f"{self.site} needs a residential exit — {proxy.NEEDS_PROXY}")

        async with httpx.AsyncClient(
            timeout=TIMEOUT, headers={"User-Agent": UA}, follow_redirects=True,
            # robots.txt is fetched through the proxy too. It has to be: the 403
            # that blocks this source is on robots.txt itself, so checking it from
            # the datacenter IP would refuse the crawl before the proxy was used.
            proxy=proxy_url,
        ) as client:
            if not await robots_allows(client, self.base, path):
                self.last_skip_reason = (
                    f"{self.site} robots.txt disallows {path} (or refused to serve "
                    f"robots.txt at all) — not crawled"
                )
                log.info("%s: %s", self.site, self.last_skip_reason)
                return []

            await asyncio.sleep(DELAY_S)
            try:
                page = await client.get(f"{self.base}{path}")
            except httpx.HTTPError as exc:
                raise RuntimeError(f"{self.site} unreachable: {exc}") from exc

            if page.status_code == 403:
                raise RuntimeError(
                    f"{self.site} returned 403 through the residential proxy. The "
                    f"datacenter-IP block was the expected cause and this route is "
                    f"meant to clear it, so a 403 here means either the proxy exit "
                    f"is itself listed or the site is refusing this path outright — "
                    f"worth checking before spending more bandwidth on retries."
                )
            if page.status_code != 200:
                raise RuntimeError(f"{self.site} returned {page.status_code} for {path}")

            html = page.text

        reviews = reviews_from_json_ld(html)
        if not html.strip():
            raise RuntimeError(f"{self.site} returned an empty body for {path}")

        cutoff = datetime.now(timezone.utc) - timedelta(days=RECENCY_DAYS)
        out: list[RawSignal] = []

        for review in reviews[: self.max_reviews]:
            rating = _rating(review)
            if rating is None or rating > NEGATIVE_AT_OR_BELOW:
                continue

            when = _when(review)
            if when is None or when < cutoff:
                continue

            text = str(review.get("reviewBody") or review.get("description") or "")
            name, role = _author(review)

            # No stable review id in JSON-LD on either site, so dedup keys on the
            # content instead. Author plus date plus the first line is stable
            # across re-fetches of the same page and distinct between reviews;
            # a positional index would re-insert everything whenever the page
            # re-orders.
            #
            # sha1, not `hash()`: Python salts string hashing per process, so the
            # built-in would produce a different id on every restart and dedup —
            # which is the entire point of this key — would silently never fire.
            fingerprint = f"{name or 'anon'}|{when.date().isoformat()}|{text[:60]}"
            ident = hashlib.sha1(fingerprint.encode("utf-8")).hexdigest()[:16]

            out.append(
                RawSignal(
                    kind="review",
                    source=self.site,
                    source_id=f"{self.site}:{slug}:{ident}",
                    observed_at=when,
                    quote=str(review.get("name") or text)[:280],
                    raw_text=text[:4000],
                    vendor=competitor,
                    company_name=None,
                    company_domain=None,
                    url=review.get("url") or f"{self.base}{path}",
                    author=name,
                    author_role=role,
                    rating=rating,
                    platform=competitor,
                    source_site=self.site,
                    country=self.country_default,
                    subscores=None,
                )
            )

        return out


class TrustRadiusCollector(_JsonLdReviewCollector):
    """TrustRadius — independent of Gartner, so not covered by Capterra's block."""

    name = "trustradius"
    site = "trustradius"
    base = "https://www.trustradius.com"
    path_template = "/products/{slug}/reviews"


class SoftwareSuggestCollector(_JsonLdReviewCollector):
    """SoftwareSuggest — Indian B2B review site.

    The most promising of the untried sources for this market specifically:
    Townscript, Explara and MeraEvents have no G2 presence at all, and an Indian
    review site is where their customers would plausibly be.
    """

    name = "softwaresuggest"
    site = "softwaresuggest"
    base = "https://www.softwaresuggest.com"
    path_template = "/{slug}/reviews"
    country_default = "India"
