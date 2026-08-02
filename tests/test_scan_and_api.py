"""Scan orchestration and the API surface.

Both had zero coverage. The scan is where a provider error can quietly abort a
run, and the API is where the cron endpoints sit — one missing auth check there
exposes a paid scan trigger to the internet.

The database is stubbed rather than run: these tests are about control flow, and
the SQL is exercised against the real schema by the migration runner.
"""

import asyncio
from datetime import datetime, timezone

import pytest

from intentdesk import db
from intentdesk.collectors import Collector, RawSignal
from intentdesk.services import companies, leads, monitoring, scan


class FakeDB:
    """Records what was written; answers reads from a scripted table."""

    def __init__(self, **answers):
        self.answers = answers
        self.executed: list[tuple] = []

    async def fetch(self, sql, *args):
        return self._lookup("fetch", sql, [])

    async def fetchrow(self, sql, *args):
        return self._lookup("fetchrow", sql, None)

    async def fetchval(self, sql, *args):
        return self._lookup("fetchval", sql, 0)

    async def execute(self, sql, *args):
        self.executed.append((sql, args))
        return "INSERT 0 1"

    def _lookup(self, kind, sql, default):
        for needle, value in self.answers.items():
            if needle in sql:
                return value
        return default


@pytest.fixture
def fake_db(monkeypatch):
    def install(**answers):
        stub = FakeDB(**answers)
        for name in ("fetch", "fetchrow", "fetchval", "execute"):
            monkeypatch.setattr(db, name, getattr(stub, name))
        return stub

    return install


class StubCollector(Collector):
    def __init__(self, name, *, requires=(), broken="", results=None, raises=None, cost=0.0):
        self.name = name
        self.kind = "review"
        self.requires = requires
        self.known_broken = broken
        self._results = results or []
        self._raises = raises
        self.last_cost_usd = cost

    async def collect(self, competitor):
        if self._raises:
            raise self._raises
        return self._results


def _signal():
    return RawSignal(
        kind="review", source="stub", source_id="stub:1",
        observed_at=datetime.now(timezone.utc), quote="too expensive",
    )


# ------------------------------------------------------------ scan orchestration


def test_collector_error_is_reported_not_raised(fake_db, monkeypatch):
    """One provider outage must not abort the whole scan — the other collectors
    still have work to do, and the run already cost money."""
    stub = fake_db(**{"FROM watchlist": [{"competitor": "Eventbrite"}]})
    monkeypatch.setattr(
        scan, "registry",
        lambda: [StubCollector("boom", raises=RuntimeError("provider 500")),
                 StubCollector("fine", results=[_signal()])],
    )
    monkeypatch.setattr(scan.preferences, "all_prefs",
                        lambda: _async({"monthly_spend_cap_usd": 5}))
    monkeypatch.setattr(scan, "rescore_all", lambda: _async({"companies_scored": 0,
                                                             "leads_created": 0}))
    monkeypatch.setattr(scan.matching, "resolve", lambda *a: _async((None, 0.0)))
    monkeypatch.setattr(scan.signals, "record", lambda **k: _async({"id": 1}))

    result = asyncio.run(scan.run())

    by_name = {c["collector"]: c for c in result["collectors_ran"]}
    assert "provider 500" in by_name["boom"]["errors"][0]
    assert by_name["fine"]["new"] == 1
    assert stub.executed, "the run must be recorded in job_runs"


def test_paid_collectors_are_skipped_once_the_cap_is_reached(fake_db, monkeypatch):
    """A code-side cap cannot stop a run that is already billing. What it can do
    is refuse to start another one."""
    fake_db(**{"FROM watchlist": [{"competitor": "Eventbrite"}],
               "FROM spend": 5.0})
    monkeypatch.setattr(
        scan, "registry",
        lambda: [StubCollector("free_one", requires=()),
                 StubCollector("paid_one", requires=("apify_token",))],
    )
    monkeypatch.setattr(scan.preferences, "all_prefs",
                        lambda: _async({"monthly_spend_cap_usd": 5}))
    monkeypatch.setattr(scan, "rescore_all", lambda: _async({"companies_scored": 0,
                                                             "leads_created": 0}))

    result = asyncio.run(scan.run())

    skipped = {s["collector"]: s["reason"] for s in result["collectors_skipped"]}
    assert "paid_one" in skipped and "spend cap" in skipped["paid_one"]
    assert "free_one" not in skipped, "a free collector must still run when the cap is hit"


def test_missing_credentials_are_named_in_the_skip_reason(fake_db, monkeypatch):
    fake_db(**{"FROM watchlist": [{"competitor": "Eventbrite"}]})
    monkeypatch.setattr(
        scan, "registry", lambda: [StubCollector("reddit", requires=("reddit_client_id",))]
    )
    monkeypatch.setattr(scan.preferences, "all_prefs",
                        lambda: _async({"monthly_spend_cap_usd": 5}))
    monkeypatch.setattr(scan, "rescore_all", lambda: _async({"companies_scored": 0,
                                                             "leads_created": 0}))

    result = asyncio.run(scan.run())
    assert "reddit_client_id" in result["collectors_skipped"][0]["reason"]


# ---------------------------------------------------------------- contactability


@pytest.mark.parametrize(
    "channel,must_mention",
    [("phone", "phone"), ("email", "contact_email"), ("both", "phone")],
)
def test_contactable_predicate_matches_the_channel(channel, must_mention):
    assert must_mention in leads.contactable_predicate(channel)


def test_unknown_channel_widens_rather_than_empties():
    """An unrecognised setting must not silently produce an empty queue."""
    assert leads.contactable_predicate("carrier-pigeon") == leads.CONTACTABLE_SQL["both"]


def test_phone_channel_does_not_require_an_email():
    """The bug this guards: requiring contact_email made every lead look
    unreachable on Apollo's free plan, which never returns one."""
    assert "contact_email" not in leads.contactable_predicate("phone")


# ------------------------------------------------------------- bulk suppression


def test_bulk_suppression_accepts_messy_input(fake_db):
    fake_db()
    result = asyncio.run(companies.suppress_bulk([
        "https://www.Acme.IN/contact",
        "priya@bluepeak.example",
        " kadam-arts.in ",
        "acme.in",          # duplicate of the first, after normalization
        "Some Company Ltd",  # a name, not a domain
        "",
    ]))
    assert result["suppressed"] == 3
    assert result["duplicates"] == 1
    assert result["rejected"] == ["Some Company Ltd"]


def test_bulk_suppression_reports_rather_than_drops_bad_rows(fake_db):
    """A do-not-contact list that silently discards entries is worse than none:
    everyone believes it is being honoured."""
    fake_db()
    result = asyncio.run(companies.suppress_bulk(["not a domain", "also bad"]))
    assert result["suppressed"] == 0
    assert result["rejected_count"] == 2


# ------------------------------------------------------------------- monitoring


def test_digest_renders_alerts_not_just_good_news():
    text = monitoring.render_digest({
        "window_days": 7, "new_leads": 0, "new_hot": 0, "awaiting": 3,
        "new_signals": 0, "approved": 0, "spend_month": 1.41,
        "top_new_leads": [],
        "alerts": [{"severity": "critical", "message": "The cron has stopped firing."}],
    })
    assert "cron has stopped firing" in text
    assert "$1.41" in text


def test_digest_says_so_when_healthy():
    text = monitoring.render_digest({
        "window_days": 7, "new_leads": 2, "new_hot": 1, "awaiting": 2,
        "new_signals": 9, "approved": 1, "spend_month": 0.0,
        "top_new_leads": [{"score": 88, "company": "Acme", "city": "Pune",
                           "vendor": "Eventbrite", "phone": "+91 20 4000 0001"}],
        "alerts": [],
    })
    assert "No alerts." in text
    assert "Acme" in text and "+91 20 4000 0001" in text


def test_lead_without_a_number_is_labelled_not_blank():
    text = monitoring.render_digest({
        "window_days": 7, "new_leads": 1, "new_hot": 0, "awaiting": 1,
        "new_signals": 1, "approved": 0, "spend_month": 0.0,
        "top_new_leads": [{"score": 60, "company": "Acme", "city": None,
                           "vendor": "Explara", "phone": None}],
        "alerts": [],
    })
    assert "no number yet" in text
    assert "location unknown" in text


# --------------------------------------------------------------------- helpers


def _async(value):
    async def run():
        return value

    return run()
