"""Trustpilot reviews, against hand-verified brand pages only.

This collector exists because of a correction. Trustpilot was written off as
"wrong audience" after Eventbrite's page returned twenty complaints from twenty
ticket buyers. That conclusion was right about Eventbrite and wrong as a rule:
Ticket Tailor's page, same site, same actor, same $0.05, returned genuine
organiser complaints ("I was having problems editing my event"). The audience is
a property of the **brand**, not the site.

So there are two gates before any money moves, and both are refusals rather than
warnings:

1. **A verified URL, never a name search.** `ti.to` name-matched Tito-Express, a
   German printer-ink retailer, and billed us for twelve reviews about
   undelivered toner. `market.TRUSTPILOT_URLS` is an allow-list; a brand absent
   from it is skipped.
2. **The segment.** A `consumer_marketplace` brand yields ticket buyers, so
   paying to scrape it is buying the wrong people's opinions.

Trustpilot's one advantage over G2 is identity: it publishes a full display name
and a country where G2 publishes "Irfan M." That is what makes
`services/identity.py` possible at all, and it is why this is the preferred
source for reviewer enrichment.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from intentdesk.collectors import Collector, RawSignal
from intentdesk.collectors.apify import ApifyRunner
from intentdesk.config import settings
from intentdesk.market import (
    TRUSTPILOT_NOTES,
    TRUSTPILOT_URLS,
    TRUSTPILOT_WRONG_AUDIENCE,
    segment_of,
)

log = logging.getLogger(__name__)

NEGATIVE_AT_OR_BELOW = 3   # stars out of 5
RECENCY_DAYS = 365         # wider than G2's 180: these pages are lower volume


class SkippedOnPurpose(Exception):
    """Not an error — a decision, carrying its reason.

    Distinct from returning an empty list, which is what "the page had no
    negative reviews" looks like. A scan summary that cannot tell those apart is
    how a permanently-skipped source gets mistaken for a quiet one.
    """


class TrustpilotReviewCollector(Collector):
    name = "trustpilot"
    kind = "review"
    requires = ("apify_token",)

    # Paid, so it never runs on the cron. This is the attribute the scheduled
    # scan filters on.
    cadence = "on_demand"
    cost_model = "per_run"
    actor = "memo23~trustpilot-scraper-ppe"

    # $0.05 per run for up to this many reviews, measured 2026-08-03 across four
    # brands. Raising it raises the bill roughly in step, so it is a constructor
    # argument rather than a constant someone edits in passing.
    def __init__(self, max_reviews: int = 20):
        self.max_reviews = max_reviews
        self.last_cost_usd = 0.0
        self.last_skip_reason: Optional[str] = None

    # -------------------------------------------------------------- the gates
    def check(self, competitor: str) -> Optional[str]:
        """Why this brand must not be scraped, or None if it may be.

        Separate from `collect()` so the API can answer "will this button work?"
        without starting a run, and so the UI can disable the control with the
        actual reason rather than letting the click fail.
        """
        key = competitor.strip().lower()

        if key not in TRUSTPILOT_URLS:
            return (f"No hand-verified Trustpilot page for {competitor}. "
                    "Add one to market.BRANDS after checking it by hand — a name "
                    "search once matched a printer-ink retailer.")

        if key in TRUSTPILOT_WRONG_AUDIENCE:
            return (f"{competitor}'s Trustpilot page is verified but its reviewers "
                    f"are ticket buyers, not organisers. "
                    f"{TRUSTPILOT_NOTES.get(key, '')}".strip())

        if segment_of(competitor) == "consumer_marketplace":
            return (f"{competitor} is a consumer marketplace, so its reviewers are "
                    "attendees. Paying to collect their complaints buys the wrong "
                    "audience.")

        return None

    async def collect(self, competitor: str) -> list[RawSignal]:
        reason = self.check(competitor)
        if reason:
            # Recorded and returned empty rather than raised: `scan.run()` treats
            # an exception as a collector failure, and a deliberate skip is not a
            # failure. The reason surfaces through `last_skip_reason`.
            self.last_skip_reason = reason
            log.info("trustpilot: skipping %s — %s", competitor, reason)
            return []

        self.last_skip_reason = None
        url = TRUSTPILOT_URLS[competitor.strip().lower()]

        items, cost = await ApifyRunner(settings.apify_token).run(
            self.actor,
            {
                # A URL, not a query. The actor also accepts a company name and
                # that input is the one that cost us the toner reviews.
                "startUrls": [{"url": url}],
                "maxItems": self.max_reviews,
                "sort": "recency",
                # Every locale's page for the same business, so an Indian
                # organiser reviewing on trustpilot.in is not missed.
                "includeAllLanguages": True,
            },
        )
        self.last_cost_usd = cost

        cutoff = datetime.now(timezone.utc) - timedelta(days=RECENCY_DAYS)
        out: list[RawSignal] = []

        for item in items:
            rating = item.get("ratingValue")
            if rating is None:
                rating = item.get("rating") or item.get("stars")
            try:
                rating = float(rating)
            except (TypeError, ValueError):
                continue
            if rating > NEGATIVE_AT_OR_BELOW:
                continue

            when = _parse_date(
                item.get("datePublished") or item.get("publishedDate")
                or item.get("date")
            )
            if when is None or when < cutoff:
                continue

            text = str(item.get("reviewBody") or item.get("text") or "")
            title = str(item.get("reviewHeadline") or item.get("title") or "")

            ident = (item.get("reviewId") or item.get("id")
                     or item.get("reviewUrl") or f"{url}:{when.isoformat()}")

            out.append(
                RawSignal(
                    kind="review",
                    # "trustpilot", not the class name: dedup is on
                    # (source, source_id), so renaming would re-insert every
                    # review already stored.
                    source="trustpilot",
                    source_id=f"trustpilot:{ident}",
                    observed_at=when,
                    quote=(title or text)[:280],
                    raw_text=text[:4000],
                    vendor=competitor,
                    # Trustpilot publishes no employer. Where the reviewer names
                    # one in the text, `drafting.analyse()` extracts it — and only
                    # when it is stated outright.
                    company_name=None,
                    company_domain=None,
                    url=item.get("reviewUrl") or url,
                    # The reason this source matters: a real display name, where
                    # G2 gives a first name and an initial. `identity.resolve()`
                    # reads this field.
                    author=item.get("reviewerName") or item.get("author"),
                    author_role=None,
                    rating=rating,
                    platform=competitor,
                    source_site="trustpilot",
                    country=item.get("reviewerCountry") or item.get("country"),
                    region=None,
                    # Trustpilot has no "switched from" question and publishes no
                    # per-dimension scores. Left absent rather than faked — a
                    # zero here would read as "rated terrible on every axis".
                    switched_from=None,
                    switched_reason=None,
                    subscores=None,
                )
            )

        return out


def _parse_date(value) -> Optional[datetime]:
    """Trustpilot dates arrive as ISO strings, sometimes without a timezone.

    A naive datetime compared against an aware cutoff raises TypeError, which
    would abort the whole run over one malformed row.
    """
    if not value:
        return None
    try:
        when = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return when if when.tzinfo else when.replace(tzinfo=timezone.utc)
