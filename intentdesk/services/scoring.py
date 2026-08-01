"""Intent scoring.

Pure functions — no database, no network — so the ranking rules can be tested
directly and changed without fear.

The shape of the model: a detected install is a standing fact and does not
decay, while every complaint or hiring signal is an event that goes stale. A
company that complained last week outranks one that complained last year, and
both outrank one we merely know runs the competitor.
"""

from datetime import datetime, timezone

# Base points per signal kind, before recency decay.
WEIGHTS = {
    "install": 30,
    "job_post": 25,
    "review": 30,
    "forum": 25,
    "vendor_news": 15,
}

SIZE_BAND_BONUS = 10
HALF_LIFE_DAYS = 180.0

# An install is current state, not an event, so it keeps its full value.
NON_DECAYING = {"install"}

HOT_AT = 80
WARM_AT = 55


def age_days(observed_at: datetime, now: datetime | None = None) -> float:
    now = now or datetime.now(timezone.utc)
    if observed_at.tzinfo is None:
        observed_at = observed_at.replace(tzinfo=timezone.utc)
    return max(0.0, (now - observed_at).total_seconds() / 86400.0)


def decay(days: float) -> float:
    """Exponential decay on a 180-day half-life."""
    return 0.5 ** (days / HALF_LIFE_DAYS)


def signal_points(signal: dict, now: datetime | None = None) -> float:
    kind = signal["kind"]
    base = WEIGHTS.get(kind, 0)
    if kind in NON_DECAYING:
        return float(base)
    return base * decay(age_days(signal["observed_at"], now))


def in_size_band(agents: int | None, low: int, high: int) -> bool:
    return agents is not None and low <= agents <= high


def score_company(
    signals: list[dict],
    agents_est: int | None = None,
    band: tuple[int, int] = (5, 200),
    now: datetime | None = None,
) -> int:
    """Total intent score, 0–100.

    Signals of the same kind are deliberately *not* summed at full value — three
    complaints is a stronger signal than one, but not three times stronger, so
    repeats after the first count half. Without this a single company spamming
    reviews would dominate the queue.
    """
    by_kind: dict[str, list[float]] = {}
    for s in signals:
        by_kind.setdefault(s["kind"], []).append(signal_points(s, now))

    total = 0.0
    for points in by_kind.values():
        points.sort(reverse=True)
        total += points[0] + 0.5 * sum(points[1:])

    if in_size_band(agents_est, *band):
        total += SIZE_BAND_BONUS

    return max(0, min(100, round(total)))


def heat_for(score: int) -> str:
    """Mirrors the generated column in Postgres. Kept here so callers can
    classify without a round trip; the database remains the source of truth."""
    if score >= HOT_AT:
        return "hot"
    if score >= WARM_AT:
        return "warm"
    return "cool"


def explain(signals: list[dict], agents_est: int | None = None,
            band: tuple[int, int] = (5, 200), now: datetime | None = None) -> list[str]:
    """Human-readable breakdown — shown in the UI and returned by the MCP tool
    so nobody has to guess why a lead ranked where it did."""
    lines = []
    for s in sorted(signals, key=lambda x: signal_points(x, now), reverse=True):
        pts = signal_points(s, now)
        days = int(age_days(s["observed_at"], now))
        lines.append(f"{s['kind']} via {s.get('source', '?')} ({days}d ago): +{pts:.1f}")
    if in_size_band(agents_est, *band):
        lines.append(f"inside target size band ({agents_est} agents): +{SIZE_BAND_BONUS}")
    return lines
