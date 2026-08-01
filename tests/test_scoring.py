from datetime import datetime, timedelta, timezone

from intentdesk.services import scoring

NOW = datetime(2026, 8, 1, tzinfo=timezone.utc)


def sig(kind, days_ago, source="test"):
    return {"kind": kind, "source": source, "observed_at": NOW - timedelta(days=days_ago)}


def test_install_alone_is_cool():
    s = scoring.score_company([sig("install", 120)], agents_est=None, now=NOW)
    assert s == 30
    assert scoring.heat_for(s) == "cool"


def test_install_does_not_decay():
    """An install is current state, not an event — a two-year-old detection is
    still worth full points as long as it is still detected."""
    fresh = scoring.score_company([sig("install", 1)], now=NOW)
    stale = scoring.score_company([sig("install", 730)], now=NOW)
    assert fresh == stale == 30


def test_events_decay_on_half_life():
    fresh = scoring.signal_points(sig("review", 0), NOW)
    half = scoring.signal_points(sig("review", 180), NOW)
    quarter = scoring.signal_points(sig("review", 360), NOW)
    assert fresh == 30
    assert round(half, 2) == 15.0
    assert round(quarter, 2) == 7.5


def test_size_band_bonus_applies_only_inside_band():
    base = [sig("install", 10)]
    assert scoring.score_company(base, agents_est=40, now=NOW) == 40
    assert scoring.score_company(base, agents_est=2, now=NOW) == 30
    assert scoring.score_company(base, agents_est=5000, now=NOW) == 30
    assert scoring.score_company(base, agents_est=None, now=NOW) == 30


def test_hot_lead_matches_the_worked_example():
    """Acme Retail: install + job post 6d + G2 review 11d, 40 agents.
    This is the example in PLAN.md and should land hot."""
    s = scoring.score_company(
        [sig("install", 120), sig("job_post", 6), sig("review", 11)],
        agents_est=40,
        now=NOW,
    )
    assert s >= scoring.HOT_AT
    assert scoring.heat_for(s) == "hot"


def test_repeat_signals_of_one_kind_count_half():
    """Three complaints beat one, but not by three times — otherwise a single
    noisy company would monopolise the queue."""
    one = scoring.score_company([sig("review", 0)], now=NOW)
    three = scoring.score_company([sig("review", 0), sig("review", 0), sig("review", 0)], now=NOW)
    assert one == 30
    assert three == 60
    assert three < 3 * one


def test_score_is_capped_and_never_negative():
    many = [sig(k, 0) for k in scoring.WEIGHTS for _ in range(5)]
    assert scoring.score_company(many, agents_est=40, now=NOW) == 100
    assert scoring.score_company([], now=NOW) == 0


def test_heat_thresholds_match_the_database():
    assert scoring.heat_for(80) == "hot"
    assert scoring.heat_for(79) == "warm"
    assert scoring.heat_for(55) == "warm"
    assert scoring.heat_for(54) == "cool"


def test_naive_datetimes_are_treated_as_utc():
    naive = {"kind": "review", "source": "t", "observed_at": datetime(2026, 7, 1)}
    assert scoring.signal_points(naive, NOW) > 0


def test_explain_lists_every_contributor():
    lines = scoring.explain(
        [sig("install", 100), sig("job_post", 5)], agents_est=40, now=NOW
    )
    assert len(lines) == 3
    assert any("job_post" in x for x in lines)
    assert any("size band" in x for x in lines)
