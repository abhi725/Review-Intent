"""Collector parsing rules.

These are the decisions that decide whether a signal becomes a real lead, a
fabricated company, or nothing at all — and all of them run before any network
call, so they are testable without spending a cent of the Apify budget.
"""

from datetime import datetime, timedelta, timezone

import pytest

from intentdesk.collectors import RETIRED, availability, registry
from intentdesk.collectors.jobs import _employer_domain, _posted_at
from intentdesk.collectors.news import _clean, _published

# --------------------------------------------------------------- job postings


def test_employer_website_becomes_the_domain():
    item = {"companyInfo": {"companyName": "Acme Events", "url": "https://www.acme-events.in/careers"}}
    assert _employer_domain(item) == "acme-events.in"


@pytest.mark.parametrize(
    "url",
    [
        "https://www.indeed.com/cmp/acme",
        "https://in.linkedin.com/company/acme",
        "https://acme.greenhouse.io/jobs/1",
        "https://www.naukri.com/acme-jobs",
    ],
)
def test_job_board_domains_are_refused(url):
    """The scan creates a company for any signal carrying a domain. Letting a
    board through would manufacture a company called Indeed and attribute every
    competitor's install base to it."""
    assert _employer_domain({"companyInfo": {"url": url}}) is None


def test_missing_or_junk_website_is_none():
    assert _employer_domain({}) is None
    assert _employer_domain({"companyInfo": {"url": ""}}) is None
    assert _employer_domain({"companyInfo": {"url": "not-a-domain"}}) is None


def test_undated_posting_is_treated_as_current():
    """Indeed reports "3 days ago" as often as a timestamp. A posting we cannot
    date is still a posting; dropping it would silently lose real signal."""
    before = datetime.now(timezone.utc) - timedelta(seconds=5)
    assert _posted_at({"postedAt": "3 days ago"}) >= before
    assert _posted_at({}) >= before


def test_parseable_date_is_used_and_made_aware():
    when = _posted_at({"postingDateParsed": "2026-06-01T10:00:00Z"})
    assert when.year == 2026 and when.month == 6
    assert when.tzinfo is not None


# ---------------------------------------------------------------- vendor news


def test_rss_html_is_stripped():
    assert _clean("<a href='x'>Eventbrite raises fees</a>") == "Eventbrite raises fees"
    assert _clean(None) == ""


def test_unparseable_pubdate_falls_back_to_now():
    import xml.etree.ElementTree as ET

    entry = ET.fromstring("<item><pubDate>not a date</pubDate></item>")
    assert _published(entry) <= datetime.now(timezone.utc)


def test_rfc822_pubdate_is_parsed():
    import xml.etree.ElementTree as ET

    entry = ET.fromstring("<item><pubDate>Tue, 07 Jul 2026 09:00:00 GMT</pubDate></item>")
    when = _published(entry)
    assert (when.year, when.month, when.day) == (2026, 7, 7)


# ------------------------------------------------------------------- registry


def test_registry_is_ordered_cheapest_first():
    """When the spend cap halts a run mid-way, what gets skipped should be the
    expensive tail, not an arbitrary slice."""
    names = [c.name for c in registry()]
    assert names.index("vendor_news") < names.index("apify_jobs")
    assert names.index("apify_jobs") < names.index("apify_g2")


def test_vendor_news_needs_no_credentials():
    news = next(c for c in registry() if c.name == "vendor_news")
    assert news.missing_credentials() == []
    assert news.available() is True


def test_capterra_is_never_reported_ready():
    """Its token is valid and the source blocks it, so credentials alone must
    not be read as working."""
    capterra = next(a for a in availability() if a["name"] == "apify_capterra")
    assert capterra["available"] is False
    assert capterra["known_broken"]


def test_retired_sources_carry_a_reason():
    assert {r["name"] for r in RETIRED} >= {"builtwith", "gmb_reviews", "linkedin_jobs"}
    assert all(r["reason"] for r in RETIRED)


def test_trustpilot_left_retirement_when_it_was_built():
    """It was retired as "wrong audience" and that turned out to be a property of
    the brand, not the site. A source cannot be both retired and registered — the
    Sources panel reads both lists and would show it twice, saying opposite things."""
    names = {r["name"] for r in RETIRED}
    assert "trustpilot" not in names
    assert "trustpilot" in {c.name for c in registry()}
