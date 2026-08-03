"""What Apollo cannot do, said out loud instead of failing at the button.

Two limits were reported as broken features, and neither was a bug:

* **Enrichment credits run out.** Apollo answers an exhausted balance with 422 and
  the reason in the body. The code reported only the status, so a spent allowance
  surfaced as "Apollo returned 422" — which reads as a broken integration and sent
  someone hunting a bug that did not exist.
* **Person endpoints are 403 on the free plan.** So a reviewer with a perfectly
  complete name is still unresolvable, and the button that offered to resolve them
  could never succeed. Company enrichment is unaffected and still works.
"""

import asyncio

import pytest

from intentdesk.config import settings
from intentdesk.services import enrichment, identity


class FakeResponse:
    def __init__(self, status_code, text="", payload=None):
        self.status_code = status_code
        self.text = text
        self._payload = payload or {}

    def json(self):
        return self._payload


class FakeClient:
    def __init__(self, response):
        self._response = response

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, *a, **k):
        return self._response


@pytest.fixture
def apollo_key(monkeypatch):
    monkeypatch.setattr(settings, "apollo_api_key", "key")


def _patch_http(monkeypatch, response):
    monkeypatch.setattr(enrichment.httpx, "AsyncClient",
                        lambda *a, **k: FakeClient(response))


# ------------------------------------------------------------ credit exhaustion
def test_exhausted_credits_say_so(monkeypatch, apollo_key):
    """The message a person reads must name the cause, not the status code."""
    _patch_http(monkeypatch, FakeResponse(
        422, '{"error":"You have insufficient credits! Upgrade at ..."}'))

    with pytest.raises(enrichment.EnrichmentUnavailable) as exc:
        asyncio.run(enrichment.fetch_organization("example.com"))

    message = str(exc.value).lower()
    assert "credits" in message, "the reason must be in the message"
    assert "exhausted" in message or "resets" in message
    assert message.strip() != "apollo returned 422"


def test_a_different_422_is_not_reported_as_credits(monkeypatch, apollo_key):
    """A malformed request is a different problem and must not be mislabelled."""
    _patch_http(monkeypatch, FakeResponse(422, '{"error":"domain is required"}'))

    with pytest.raises(enrichment.EnrichmentUnavailable) as exc:
        asyncio.run(enrichment.fetch_organization(""))
    assert "domain is required" in str(exc.value)


@pytest.mark.parametrize("status", [400, 500, 502])
def test_other_failures_carry_apollos_own_words(monkeypatch, apollo_key, status):
    """Previously every non-200 collapsed to the bare status."""
    _patch_http(monkeypatch, FakeResponse(status, '{"error":"something specific"}'))

    with pytest.raises(enrichment.EnrichmentUnavailable) as exc:
        asyncio.run(enrichment.fetch_organization("example.com"))
    assert "something specific" in str(exc.value)
    assert str(status) in str(exc.value)


def test_403_still_reports_the_plan(monkeypatch, apollo_key):
    _patch_http(monkeypatch, FakeResponse(403, '{"error":"forbidden"}'))
    with pytest.raises(enrichment.EnrichmentUnavailable, match="plan"):
        asyncio.run(enrichment.fetch_organization("example.com"))


# --------------------------------------------------------------- the plan gate
def test_plan_gate_is_off_by_default():
    """Measured: every Apollo person endpoint answers 403 on the free plan. The
    default has to match what was measured, not what would be convenient."""
    assert settings.apollo_people_enabled is False


def test_assess_refuses_and_flags_when_people_are_unavailable(monkeypatch):
    async def fake_fetchrow(sql, *args):
        if "reviewer_identity" in sql:
            return None
        return {"id": 1, "author": "Kimberly Ellison", "country": "US",
                "source_site": "g2", "platform": "Eventbrite",
                "company_id": 7, "matched_company": "Acme Events"}

    monkeypatch.setattr(identity.db, "fetchrow", fake_fetchrow)
    monkeypatch.setattr(settings, "apollo_people_enabled", False)

    out = asyncio.run(identity.assess(1))
    assert out["plan_blocked"] is True
    assert out["allowed"] is False
    assert "403" in out["refusal"]
    assert "APOLLO_PEOPLE_ENABLED" in out["refusal"], (
        "the refusal should say what to change"
    )


def test_plan_refusal_outranks_a_thin_name(monkeypatch):
    """Both can apply. "your account cannot do this" is the more actionable one."""
    async def fake_fetchrow(sql, *args):
        if "reviewer_identity" in sql:
            return None
        # An initial for a surname: normally a `low` tier refusal of its own.
        return {"id": 2, "author": "Kimberly E.", "country": "US",
                "source_site": "g2", "platform": "Eventbrite",
                "company_id": None, "matched_company": None}

    monkeypatch.setattr(identity.db, "fetchrow", fake_fetchrow)
    monkeypatch.setattr(settings, "apollo_people_enabled", False)

    out = asyncio.run(identity.assess(2))
    assert out["plan_blocked"] is True
    assert "403" in out["refusal"]


def test_resolve_refuses_without_storing_a_low_verdict(monkeypatch):
    """A plan refusal must not be cached as `low`.

    A `low` verdict is permanent by design, so caching a plan refusal would mean
    that after upgrading every row returns the stale refusal for free and never
    retries — the cache would outlive the reason for it.
    """
    async def fake_fetchrow(sql, *args):
        if "reviewer_identity" in sql:
            return None
        return {"id": 3, "author": "Kimberly Ellison", "country": "US",
                "source_site": "g2", "platform": "Eventbrite",
                "company_id": 7, "matched_company": "Acme Events"}

    stored = []

    async def fake_store(*a, **k):
        stored.append((a, k))
        return {}

    monkeypatch.setattr(identity.db, "fetchrow", fake_fetchrow)
    monkeypatch.setattr(identity, "_store", fake_store)
    monkeypatch.setattr(settings, "apollo_people_enabled", False)

    out = asyncio.run(identity.resolve(3))
    assert out["refused"] is True
    assert out["cost_usd"] == 0.0
    assert not stored, "a plan refusal must not be written to reviewer_identity"


def test_enabling_the_plan_clears_the_flag(monkeypatch):
    async def fake_fetchrow(sql, *args):
        if "reviewer_identity" in sql:
            return None
        return {"id": 4, "author": "Kimberly Ellison", "country": "US",
                "source_site": "g2", "platform": "Eventbrite",
                "company_id": 7, "matched_company": "Acme Events"}

    monkeypatch.setattr(identity.db, "fetchrow", fake_fetchrow)
    monkeypatch.setattr(settings, "apollo_people_enabled", True)

    out = asyncio.run(identity.assess(4))
    assert out["plan_blocked"] is False
    assert out["refusal"] is None
