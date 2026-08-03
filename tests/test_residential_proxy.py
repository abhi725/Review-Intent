"""The residential proxy gate, and the removal of Reddit.

Three sources were blocked by the same thing — a datacenter-IP 403 — and are
unblocked by the same thing. What has to stay true is that turning the proxy on
is a *deliberate, paid* act: the sources must report blocked until it is
configured, must refuse to start a billable run without it, and must never end
up on the free schedule now that they cost money.

Measured 2026-08-03 and the reason this is gated rather than simply enabled: a
free Apify account authenticates against the proxy and is then refused with 403
on every group, including the datacenter group its own plan lists. So the code
path cannot be tested into working without the paid plan, and the honest state
until then is "blocked", not "ready".
"""

import asyncio

import pytest

from intentdesk.collectors import (
    PRICED_ACTION,
    availability,
    get as get_collector,
    registry,
)
from intentdesk.collectors import proxy
from intentdesk.collectors.apify import CapterraReviewCollector
from intentdesk.collectors.reviews_b2b import (
    SoftwareSuggestCollector,
    TrustRadiusCollector,
)
from intentdesk.config import settings
from intentdesk.services import spend

PROXY_GATED = (CapterraReviewCollector, TrustRadiusCollector, SoftwareSuggestCollector)


@pytest.fixture
def proxy_on(monkeypatch):
    monkeypatch.setattr(settings, "apify_residential_proxy", True)
    monkeypatch.setattr(settings, "apify_proxy_password", "x" * 48)


@pytest.fixture
def proxy_off(monkeypatch):
    monkeypatch.setattr(settings, "apify_residential_proxy", False)
    monkeypatch.setattr(settings, "apify_proxy_password", "")


# ------------------------------------------------------------------ the gate
def test_flag_without_password_is_not_enabled(monkeypatch):
    """The flag alone would point every request at a proxy that refuses it,
    turning a clear "blocked" into a run that fails halfway through."""
    monkeypatch.setattr(settings, "apify_residential_proxy", True)
    monkeypatch.setattr(settings, "apify_proxy_password", "")
    assert proxy.enabled() is False
    assert proxy.url() is None
    assert proxy.actor_configuration() is None


def test_password_without_flag_is_not_enabled(monkeypatch):
    monkeypatch.setattr(settings, "apify_residential_proxy", False)
    monkeypatch.setattr(settings, "apify_proxy_password", "x" * 48)
    assert proxy.enabled() is False


def test_url_uses_the_residential_group_and_the_proxy_password(proxy_on):
    url = proxy.url()
    assert url.startswith("http://groups-RESIDENTIAL:")
    assert "proxy.apify.com:8000" in url
    # The API token gets 407 here. If this ever starts carrying the token, the
    # proxy stops working and the reason is invisible from the error.
    assert settings.apify_proxy_password in url
    assert settings.apify_token not in url or not settings.apify_token


def test_actor_configuration_never_leaks_the_password(proxy_on):
    """Actors run on Apify's own infrastructure and take the group by name."""
    config = proxy.actor_configuration()
    assert config == {"useApifyProxy": True, "apifyProxyGroups": ["RESIDENTIAL"]}
    assert settings.apify_proxy_password not in str(config)


# -------------------------------------------------- what the sources report
@pytest.mark.parametrize("cls", PROXY_GATED, ids=[c.name for c in PROXY_GATED])
def test_blocked_without_the_proxy(cls, proxy_off):
    coll = cls()
    assert coll.known_broken, f"{cls.name} must report why it cannot run"
    assert "residential" in coll.known_broken.lower()
    assert coll.available() is False


@pytest.mark.parametrize("cls", PROXY_GATED, ids=[c.name for c in PROXY_GATED])
def test_not_blocked_with_the_proxy(cls, proxy_on):
    assert cls().known_broken in (None, "")


def test_capterra_becomes_available_with_the_proxy(proxy_on, monkeypatch):
    """Capterra needs no slug allow-list, so the proxy is the only thing between
    it and a working button — this is the one the user can click and test."""
    monkeypatch.setattr(settings, "apify_token", "tok")
    assert CapterraReviewCollector().available() is True


@pytest.mark.parametrize("cls", (TrustRadiusCollector, SoftwareSuggestCollector),
                         ids=("trustradius", "softwaresuggest"))
def test_b2b_still_needs_a_verified_slug_even_with_the_proxy(cls, proxy_on):
    """A guessed slug once returned a German printer-ink retailer's reviews. The
    proxy clears the network block; it does not license a name search."""
    coll = cls()
    assert coll.available() is False, (
        "the proxy must not be enough on its own — a slug still has to be "
        "hand-verified, or this source can write another vendor's complaints "
        "into the signal table under our competitor's name"
    )
    assert "slug" in coll.check("Eventbrite").lower()


# --------------------------------------------- billable work stays off the cron
@pytest.mark.parametrize("cls", PROXY_GATED, ids=[c.name for c in PROXY_GATED])
def test_paid_sources_are_on_demand(cls):
    coll = cls()
    assert coll.cost_model != "free", f"{cls.name} bills for bandwidth or events"
    assert coll.cadence == "on_demand", (
        f"{cls.name} costs money — a scheduled cadence would let it run "
        "unattended, which is the spending pattern this design prevents"
    )


@pytest.mark.parametrize("cls", PROXY_GATED, ids=[c.name for c in PROXY_GATED])
def test_every_gated_source_is_priced(cls):
    action = PRICED_ACTION.get(cls.name)
    assert action, f"{cls.name} bills but names no priced action"
    est = spend.estimate(action, 1)
    assert est["estimated_usd"] > 0, "a paid button must not render a zero price"
    # These have never completed a run, so the price is an estimate and the UI
    # renders it with a "~". Claiming `measured` would make a guess look verified.
    assert est["measured"] is False


def test_capterra_refuses_to_bill_without_a_proxy(proxy_off, monkeypatch):
    """The actor exits SUCCEEDED on a 403, so starting it without a residential
    exit pays for a run that returns nothing."""
    monkeypatch.setattr(settings, "apify_token", "tok")
    with pytest.raises(RuntimeError, match="residential"):
        asyncio.run(CapterraReviewCollector().collect("Eventbrite"))


# ------------------------------------------------------------ Reddit is gone
def test_reddit_is_not_a_collector():
    """Removed rather than deactivated: the account cannot get API access, and a
    source that can never run is worse than no source — it reads as a gap to be
    filled by the next person."""
    assert get_collector("reddit") is None
    assert "reddit" not in {c.name for c in registry()}
    assert "reddit" not in {s["name"] for s in availability()}
    assert "reddit" not in PRICED_ACTION


def test_no_reddit_settings_remain():
    for name in ("reddit_client_id", "reddit_client_secret", "reddit_user_agent"):
        assert not hasattr(settings, name), f"{name} outlived the collector"


def test_no_reddit_price_remains():
    assert "collect_reddit" not in spend.PRICES
