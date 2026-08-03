"""The fields the G2 collector receives and used to discard.

Every expectation here is pinned to a real payload. On 2026-08-03 two Apify
datasets from earlier paid runs were re-read (free) and the actor's field list
was recorded exactly. The collector had been reading two fields that do not
exist in it — `reviewerJobTitle` and `reviewLink` — so `author_role` was NULL on
every row ever stored while looking like a field that was merely often empty.

The sample below is a verbatim record from dataset 9b0eQswNwawOdAVua.
"""

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from intentdesk.collectors.apify import G2ReviewCollector
from intentdesk.services import export

# Verbatim shape of what automation-lab~g2-scraper returns. Do not "tidy" this
# by adding fields the actor does not send — the point is that it does not.
REAL_ITEM = {
    "reviewId": 13187003,
    "title": "The Best Tool for Event Visibility, if You Can Handle the Fees",
    "reviewText": "Their reach is great. The reporting isn't great, and they "
                  "don't integrate well with other systems.",
    "starRating": 3,
    "nps": 6,
    "publishedAt": "2026-07-31T12:30:12.481Z",
    "submittedAt": "2026-07-30T13:44:22.882Z",
    "reviewerName": "Jan Sytze H.",
    "country": "United States",
    "region": "North America",
    "companySegment": 179,
    "industry": 1001392,
    "productId": 2743,
    "productName": "Eventbrite",
    "productSlug": "eventbrite",
    "url": "https://www.g2.com/products/eventbrite/reviews/13187003",
    "easeOfUse": 4,
    "easeOfSetup": 6,
    "qualityOfSupport": 7,
    "meetsRequirements": 6,
    "switchedFromOtherProduct": "yes",
    "switchedReason": "Fees were too high",
}


def _map(item):
    """Run the collector's mapping without touching the network."""
    c = G2ReviewCollector()
    fresh = datetime.now(timezone.utc) - timedelta(days=1)
    item = {**item, "publishedAt": fresh.isoformat().replace("+00:00", "Z")}

    async def fake_run(actor, payload, timeout_s=240):
        return [item], 0.0

    import intentdesk.collectors.apify as mod
    original = mod.ApifyRunner.run
    mod.ApifyRunner.run = fake_run
    try:
        return asyncio.run(c.collect("Eventbrite"))
    finally:
        mod.ApifyRunner.run = original


@pytest.fixture
def signal(monkeypatch):
    monkeypatch.setattr("intentdesk.config.settings.apify_token", "test-token")
    monkeypatch.setattr("intentdesk.collectors.apify.G2_SLUGS",
                        {"eventbrite": "eventbrite"})
    out = _map(REAL_ITEM)
    assert len(out) == 1, "a 3-star review is negative and must be kept"
    return out[0]


def test_platform_comes_from_the_payload_not_the_query(signal):
    """`productName` was being discarded, so the feed had no way to group by
    competitor except by guessing from whichever watchlist row triggered the
    scan."""
    assert signal.platform == "Eventbrite"
    assert signal.source_site == "g2"


def test_author_role_is_none_because_the_actor_never_sends_one(signal):
    """Not an oversight — an assertion about the payload. If a future actor
    version adds a job title, this test failing is the correct alarm."""
    assert "reviewerJobTitle" not in REAL_ITEM
    assert "reviewerRole" not in REAL_ITEM
    assert signal.author_role is None
    assert signal.author == "Jan Sytze H."


def test_url_is_read_from_url_not_reviewlink(signal):
    """`reviewLink` does not exist; the old mapping only worked by falling
    through to `url`."""
    assert "reviewLink" not in REAL_ITEM
    assert signal.url.endswith("/reviews/13187003")


def test_switched_from_is_captured(signal):
    """A reviewer stating in writing that they changed platforms, and why —
    the strongest buying signal in the payload, previously dropped."""
    assert signal.switched_from == "yes"
    assert signal.switched_reason == "Fees were too high"


def test_no_switch_is_stored_as_null_not_the_string_no(monkeypatch):
    """'no' is not a vendor name. Stored literally it would make every
    non-switcher look like a switcher to any `IS NOT NULL` filter."""
    monkeypatch.setattr("intentdesk.config.settings.apify_token", "test-token")
    monkeypatch.setattr("intentdesk.collectors.apify.G2_SLUGS",
                        {"eventbrite": "eventbrite"})
    out = _map({**REAL_ITEM, "switchedFromOtherProduct": "no",
                "switchedReason": None})
    assert out[0].switched_from is None


def test_subscores_omit_dimensions_the_actor_did_not_score(signal):
    """An absent dimension must stay absent. Defaulted to zero it would read as
    'rated terrible' to any scoring that trusts the number."""
    assert signal.subscores["easeOfUse"] == 4
    assert signal.subscores["qualityOfSupport"] == 7
    assert "easeOfAdmin" not in signal.subscores


def test_country_survives_for_the_india_filter(signal):
    assert signal.country == "United States"
    assert signal.region == "North America"


def test_company_stays_unmatched_because_g2_publishes_no_employer(signal):
    """`companySegment` is a size bucket and `industry` a taxonomy id. Neither
    identifies a company, and treating either as one would mean contacting a
    business about a complaint it never made."""
    assert signal.company_name is None
    assert signal.company_domain is None


def test_source_stays_g2_so_dedup_still_matches_stored_rows(signal):
    """Dedup is on (source, source_id). Renaming this to the collector's own
    name would re-insert every review already collected."""
    assert signal.source == "g2"
    assert signal.source_id == "g2:13187003"


# ------------------------------------------------------------------ export


def test_empty_export_refuses_instead_of_writing_a_header_only_file(monkeypatch):
    """Reported as "export is giving blank files". The writer was correct; the
    queue was empty. A file containing only headers downloads cleanly, opens
    cleanly, and explains nothing."""
    async def no_rows(*a, **kw):
        return []

    monkeypatch.setattr(export, "_all_rows", no_rows)

    with pytest.raises(export.NothingToExport) as csv_err:
        asyncio.run(export.leads_csv())
    with pytest.raises(export.NothingToExport) as xlsx_err:
        asyncio.run(export.leads_xlsx())

    assert "no leads" in str(csv_err.value).lower()
    assert str(xlsx_err.value)


def test_refusal_names_the_filter_that_excluded_everything(monkeypatch):
    """"No leads at all" and "none matching this filter" need different fixes,
    so they must not share a message."""
    async def no_rows(*a, **kw):
        return []

    monkeypatch.setattr(export, "_all_rows", no_rows)
    with pytest.raises(export.NothingToExport) as err:
        asyncio.run(export.leads_csv(status="contacted", heat="hot"))
    assert "status=contacted" in err.value.reason
    assert "heat=hot" in err.value.reason
