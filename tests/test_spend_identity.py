"""Spend control, reviewer identity, and the two gates that refuse before paying.

These three belong in one file because they are one mechanism seen from three
angles: a paid action must state its price, be refusable, and be attributable. The
tests that matter are the refusals — a gate that only ever says yes is not a gate,
and every one of these was written to fail if the corresponding guard is deleted.
"""

import asyncio

import pytest

from intentdesk import db, market
from intentdesk.collectors.trustpilot import TrustpilotReviewCollector
from intentdesk.services import identity, preferences, spend


def _async(value):
    async def run(*a, **kw):
        return value
    return run


@pytest.fixture
def cap(monkeypatch):
    """Set the monthly cap and the month-to-date total."""
    def install(cap_usd: float, spent_usd: float):
        monkeypatch.setattr(preferences, "all_prefs",
                            _async({"monthly_spend_cap_usd": cap_usd}))
        monkeypatch.setattr(db, "fetchval", _async(spent_usd))
    return install


# ------------------------------------------------------------- the price list


def test_every_price_says_whether_it_was_measured():
    """A guess presented as a measurement becomes a number someone plans around.
    `measured: False` is what makes the UI render a "~"."""
    for action, price in spend.PRICES.items():
        assert price["note"], f"{action} has no provenance note"
        assert isinstance(price["measured"], bool)
        assert price["unit"], f"{action} does not say what a unit is"


def test_a_per_unit_price_multiplies():
    one = spend.estimate("collect_g2", 1)
    twenty = spend.estimate("collect_g2", 20)
    assert twenty["estimated_usd"] == pytest.approx(one["estimated_usd"] * 20)
    assert "$1.20" in twenty["label"]


def test_an_unregistered_action_is_unknown_rather_than_free():
    """The dangerous default. A new collector with no price entry must not render
    a button reading "free"."""
    est = spend.estimate("collect_something_new", 5)
    assert est["free"] is False
    assert est["measured"] is False
    assert "unknown" in est["label"]


def test_an_unmeasured_price_is_marked_with_a_tilde():
    est = spend.estimate("enrich_reviewer", 1)
    assert est["measured"] is False
    assert "~" in est["label"]


# ------------------------------------------------------------------- the gate


def test_free_actions_are_never_gated(cap):
    cap(5.0, 5.0)   # cap fully spent
    est = asyncio.run(spend.guard("collect_news", 1))
    assert est["free"] is True


def test_the_gate_refuses_once_the_cap_is_spent(cap):
    cap(5.0, 5.0)
    with pytest.raises(spend.SpendRefused) as exc:
        asyncio.run(spend.guard("collect_trustpilot", 1))
    assert "already spent" in exc.value.reason
    assert exc.value.as_dict()["cap_usd"] == 5.0


def test_the_gate_refuses_a_call_that_would_cross_the_cap(cap):
    """Not just "are we over" but "would this take us over". Checking only the
    former lets one large run through at 99% of budget."""
    cap(5.0, 4.90)
    with pytest.raises(spend.SpendRefused) as exc:
        asyncio.run(spend.guard("collect_g2", 20))     # $1.20
    assert "past the $5.00 cap" in exc.value.reason


def test_a_call_that_fits_is_allowed(cap):
    cap(5.0, 1.00)
    cleared = asyncio.run(spend.guard("collect_trustpilot", 1))
    assert cleared["estimated_usd"] == 0.05
    assert cleared["spend_state"]["exhausted"] is False


def test_override_passes_the_cap_and_says_so(cap):
    cap(5.0, 5.0)
    cleared = asyncio.run(spend.guard("collect_trustpilot", 1, override=True))
    assert cleared["override"] is True


def test_the_warning_fires_before_the_money_is_gone(cap):
    cap(5.0, 4.20)      # 84%
    state = asyncio.run(spend.month_to_date())
    assert state["warning"] is True and state["exhausted"] is False

    cap(5.0, 1.00)      # 20%
    assert asyncio.run(spend.month_to_date())["warning"] is False


def test_a_zero_cap_is_treated_as_no_budget_rather_than_no_limit(cap):
    """Division by the cap is how "0" becomes "unlimited" in a percentage. A cap
    of zero has to mean stop."""
    cap(0.0, 0.0)
    state = asyncio.run(spend.month_to_date())
    assert state["exhausted"] is True
    with pytest.raises(spend.SpendRefused):
        asyncio.run(spend.guard("collect_trustpilot", 1))


# ------------------------------------------------------ Trustpilot gating (C1)


def test_a_brand_with_no_verified_page_is_refused():
    coll = TrustpilotReviewCollector()
    reason = coll.check("Humanitix")
    assert reason and "hand-verified" in reason


def test_a_consumer_marketplace_is_refused_even_with_a_verified_page():
    """Eventbrite's page is real and was paid for once. Its reviewers were twenty
    ticket buyers out of twenty, so the page existing is not a reason to read it
    again."""
    coll = TrustpilotReviewCollector()
    assert market.TRUSTPILOT_URLS.get("eventbrite"), "the fixture assumes a verified page"
    reason = coll.check("Eventbrite")
    assert reason and "ticket buyers" in reason


def test_an_organiser_saas_brand_with_a_verified_page_is_allowed():
    coll = TrustpilotReviewCollector()
    assert coll.check("Ticket Tailor") is None


def test_the_refusal_returns_no_rows_and_records_why():
    """A refusal is not an error — raising would make `scan.run()` report a
    collector failure. But it must not look like an empty week either."""
    coll = TrustpilotReviewCollector()
    # Eventbrite, not BookMyShow: BookMyShow trips the *first* gate (no verified
    # page), and this test is about the second one, where the page is real and the
    # audience is wrong. Using an unverified brand would have passed while testing
    # nothing about the segment rule.
    rows = asyncio.run(coll.collect("Eventbrite"))
    assert rows == []
    assert coll.last_skip_reason and "ticket buyers" in coll.last_skip_reason


def test_the_toner_incident_is_recorded_as_data():
    """`ti.to` matched a German printer-ink retailer. Keeping the finding in code
    is what stops the next person assuming a brand's domain is its slug."""
    assert "tito" in market.TRUSTPILOT_REJECTED
    assert "printer-ink" in market.TRUSTPILOT_REJECTED["tito"]
    assert "tito" not in market.TRUSTPILOT_URLS


# ------------------------------------------------------------ name shapes (C3)


@pytest.mark.parametrize("name,usable", [
    ("Irfan M.", False),          # G2's privacy trim — no lookup can undo it
    ("Jan Sytze H", False),
    ("Michelle", False),          # no surname
    ("Anonymous", False),
    ("Trustpilot User", False),
    ("Michelle Evans", True),     # usable, but common
    ("Abi Lupton-Levy", True),
])
def test_which_names_can_be_looked_up_at_all(name, usable):
    assert identity.name_shape(name)["usable"] is usable


def test_a_common_surname_is_not_rare():
    assert identity.name_shape("Michelle Evans")["rare"] is False
    assert identity.name_shape("Rahul Sharma")["rare"] is False


def test_a_hyphenated_surname_counts_as_rare():
    assert identity.name_shape("Abi Lupton-Levy")["rare"] is True


def test_no_name_carries_its_own_reason():
    shape = identity.name_shape("Irfan M.")
    assert "privacy trim" in shape["reason"]


# ----------------------------------------------------------------- tiers (C3)


def test_high_needs_a_rare_name_and_a_named_employer():
    shape = identity.name_shape("Abi Lupton-Levy")
    level, reason = identity.tier(shape, "Kadam Arts", country_matches=True)
    assert level == "high" and "Kadam Arts" in reason


def test_a_country_mismatch_drops_high_to_medium():
    """A same-name person in another country is the failure this catches — the
    organiser-resolution stage hit exactly this when "Aadish jain" resolved to
    NYU Langone Health."""
    shape = identity.name_shape("Abi Lupton-Levy")
    level, _ = identity.tier(shape, "Kadam Arts", country_matches=False)
    assert level == "medium"


def test_a_rare_name_with_no_employer_is_held_not_used():
    shape = identity.name_shape("Abi Lupton-Levy")
    level, _ = identity.tier(shape, None, country_matches=True)
    assert level == "medium"


def test_a_common_name_with_no_employer_is_low():
    shape = identity.name_shape("Michelle Evans")
    level, reason = identity.tier(shape, None, country_matches=True)
    assert level == "low"
    assert "not contacted" in reason


def test_an_unusable_name_is_low_whatever_else_is_known():
    """No employer and no country agreement can rescue a missing surname."""
    shape = identity.name_shape("Irfan M.")
    level, _ = identity.tier(shape, "Acme Events", country_matches=True)
    assert level == "low"


def test_unknown_country_is_not_a_mismatch():
    assert identity._country_agrees("IN", None) is None
    assert identity._country_agrees(None, "India") is None
    assert identity._country_agrees("IN", "India") is True
    assert identity._country_agrees("IN", "United States") is False


# --------------------------------------------------- refusing before spending


def test_a_low_name_is_refused_without_calling_apollo(monkeypatch):
    """The whole point of the pre-flight tier. Spending a credit to be told the
    surname was an initial is money for information we already had."""
    called = []

    async def never(*a, **kw):
        called.append(a)
        return None, 0.0

    monkeypatch.setattr(identity, "_apollo_people_match", never)
    monkeypatch.setattr(identity, "assess", _async({
        "signal_id": 1, "display_name": "Irfan M.", "country": "IN",
        "matched_company": None, "cached": None,
        "name_shape": identity.name_shape("Irfan M."),
        "predicted_tier": "low", "reason": "surname trimmed to an initial",
    }))
    monkeypatch.setattr(identity, "_store", _async({"signal_id": 1, "confidence": "low"}))

    result = asyncio.run(identity.resolve(1))
    assert result["refused"] is True
    assert result["cost_usd"] == 0.0
    assert called == [], "Apollo must not be called for a low-tier name"


def test_a_cached_identity_is_free_on_the_second_click(monkeypatch):
    called = []

    async def never(*a, **kw):
        called.append(a)
        return None, 0.0

    monkeypatch.setattr(identity, "_apollo_people_match", never)
    monkeypatch.setattr(identity, "assess", _async({
        "signal_id": 1, "cached": {"signal_id": 1, "confidence": "high",
                                   "full_name": "Abi Lupton-Levy"},
        "predicted_tier": "high", "reason": "", "display_name": "Abi Lupton-Levy",
        "country": "GB", "matched_company": "Kadam Arts",
        "name_shape": identity.name_shape("Abi Lupton-Levy"),
    }))

    result = asyncio.run(identity.resolve(1))
    assert result["cached"] is True and result["cost_usd"] == 0.0
    assert called == []
