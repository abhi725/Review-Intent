"""Job postings that name a competitor.

This is the most valuable collector in the set, and the reason is not signal
strength but **identity**. G2 publishes no company name; Reddit posts are
pseudonymous; Google News talks about the vendor, not their customers. A job
posting names the employer and, with `parseCompanyDetails`, their website — so
this is the only free source that produces a *company*, and a company is what
the rest of the pipeline needs to do anything at all.

The signal itself is also the best one available: a posting that names the
platform proves the install is live, that someone is paid to operate it, and
that there is budget in the room.

Actor: `misceres/indeed-scraper`, pay-per-event at $0.006 per listing on the
free tier (verified against the live API on 2026-08-02, 1.8M runs). Flat-rate
LinkedIn actors were rejected for the same reason `imadjourney/capterra` was —
a $25–39/month subscription does not fit a $5 account.

UNTESTED against live output. The field names below come from the actor's
documented output; every one is read defensively, and the first live run is the
test. Cost is bounded by `max_per_competitor` before it is bounded by anything
else, so a wrong guess about field names costs one cheap run, not the month.
"""

from datetime import datetime, timedelta, timezone

from intentdesk.collectors import Collector, RawSignal
from intentdesk.collectors.apify import ApifyRunner
from intentdesk.config import settings
from intentdesk.market import JOB_LOCATIONS, JOB_QUERY_TEMPLATE, JOB_ROLE_TERMS
from intentdesk.services.matching import normalize_domain

RECENCY_DAYS = 120

# Sites that host postings on behalf of others. Their domain is not the
# employer's, and recording it would create a "company" called Indeed with
# every competitor's install attributed to it.
ATS_AND_BOARDS = {
    "indeed.com", "linkedin.com", "naukri.com", "glassdoor.com", "monster.com",
    "shine.com", "timesjobs.com", "foundit.in", "greenhouse.io", "lever.co",
    "workable.com", "smartrecruiters.com", "bamboohr.com", "recruitee.com",
    "zohorecruit.com", "keka.com", "darwinbox.com", "freshteam.com",
}


def _first(item: dict, *keys):
    for key in keys:
        value = item.get(key)
        if value:
            return value
    return None


def _employer_domain(item: dict) -> str | None:
    """The employer's own domain, or None.

    Returning a board's domain would be worse than returning nothing: the scan
    creates a company row for any signal that carries a domain, so one bad value
    manufactures a fake company that then accumulates every competitor's signals.
    """
    info = item.get("companyInfo") or {}
    raw = _first(info, "url", "website", "companyUrl") or _first(item, "companyWebsite")
    if not raw:
        return None
    domain = normalize_domain(str(raw))
    if not domain or "." not in domain:
        return None
    if any(domain == b or domain.endswith("." + b) for b in ATS_AND_BOARDS):
        return None
    return domain


def _posted_at(item: dict) -> datetime:
    """Indeed reports relative ages ("3 days ago") as often as timestamps, so
    an unparseable date means *now* rather than a skipped row — a posting we
    cannot date is still a posting, and the recency filter is the only thing
    that would drop it."""
    raw = _first(item, "postingDateParsed", "postedAt", "date", "scrapedAt")
    if raw:
        try:
            when = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
            return when if when.tzinfo else when.replace(tzinfo=timezone.utc)
        except (TypeError, ValueError):
            pass
    return datetime.now(timezone.utc)


class JobPostCollector(Collector):
    name = "apify_jobs"
    kind = "job_post"
    requires = ("apify_token",)
    actor = "misceres~indeed-scraper"

    # 15 per competitor across 9 competitors is ~$0.81 a scan against a $5
    # month. Raising this is the single fastest way to exhaust the budget.
    def __init__(self, max_per_competitor: int = 15):
        self.max_per_competitor = max_per_competitor
        self.last_cost_usd = 0.0

    async def collect(self, competitor: str) -> list[RawSignal]:
        self.last_cost_usd = 0.0
        cutoff = datetime.now(timezone.utc) - timedelta(days=RECENCY_DAYS)
        out: list[RawSignal] = []
        seen: set[str] = set()

        for location in JOB_LOCATIONS:
            items, cost = await ApifyRunner(settings.apify_token).run(
                self.actor,
                {
                    "position": JOB_QUERY_TEMPLATE.format(competitor=competitor),
                    "country": settings.target_country,
                    "location": location,
                    "maxItemsPerSearch": self.max_per_competitor,
                    "parseCompanyDetails": True,
                    "saveOnlyUniqueItems": True,
                },
            )
            self.last_cost_usd += cost

            for item in items:
                title = str(_first(item, "positionName", "title", "position") or "")
                description = str(_first(item, "description", "descriptionText") or "")
                haystack = f"{title}\n{description}".lower()

                # The search is a keyword match, so it also returns postings that
                # merely mention the vendor in a benefits list or a boilerplate
                # tech stack. Requiring an operating role is what keeps this a
                # signal about ticketing rather than a signal about recruiting.
                if competitor.lower() not in haystack:
                    continue
                if not any(term in haystack for term in JOB_ROLE_TERMS):
                    continue

                when = _posted_at(item)
                if when < cutoff:
                    continue

                ident = str(_first(item, "id", "jobKey", "url") or title)
                if ident in seen:
                    continue
                seen.add(ident)

                company_name = _first(item, "company", "companyName") or (
                    item.get("companyInfo") or {}
                ).get("companyName")

                out.append(
                    RawSignal(
                        kind="job_post",
                        source="indeed",
                        source_id=f"indeed:{ident}",
                        observed_at=when,
                        quote=title[:280],
                        raw_text=f"{title}\n\n{description}"[:4000],
                        company_name=str(company_name) if company_name else None,
                        company_domain=_employer_domain(item),
                        city=_first(item, "location", "city"),
                        vendor=competitor,
                    )
                )

        return out
