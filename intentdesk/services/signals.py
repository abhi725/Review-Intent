from datetime import datetime
from typing import Optional

from intentdesk import db

KINDS = ("install", "job_post", "review", "forum", "vendor_news")


async def list_signals(
    kind: Optional[str] = None,
    matched: Optional[bool] = None,
    since: Optional[datetime] = None,
    limit: int = 100,
) -> list[dict]:
    """The signal feed. `matched=False` returns signals we could not tie to a
    tracked company — they still matter, they prove the collector is alive."""
    return await db.fetch(
        """
        SELECT s.id, s.kind, s.source, s.observed_at, s.quote, s.weight,
               s.matched_confidence, s.company_id,
               c.name AS company, c.domain
        FROM signals s
        LEFT JOIN companies c ON c.id = s.company_id
        WHERE ($1::text IS NULL OR s.kind = $1)
          AND ($2::bool IS NULL
               OR ($2 IS TRUE AND s.company_id IS NOT NULL)
               OR ($2 IS FALSE AND s.company_id IS NULL))
          AND ($3::timestamptz IS NULL OR s.observed_at >= $3)
        ORDER BY s.observed_at DESC
        LIMIT $4
        """,
        kind,
        matched,
        since,
        min(limit, 500),
    )


async def record(
    kind: str,
    source: str,
    source_id: str,
    observed_at: datetime,
    company_id: Optional[int] = None,
    raw_text: Optional[str] = None,
    quote: Optional[str] = None,
    weight: int = 0,
    matched_confidence: float = 0.0,
) -> Optional[dict]:
    """Store a signal, ignoring one we have already seen.

    Dedup is on (source, source_id) so a rescan of the same G2 page cannot
    re-score a company or trigger a second draft.
    """
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {KINDS}, got {kind!r}")

    return await db.fetchrow(
        """
        INSERT INTO signals (company_id, kind, source, source_id, observed_at,
                             raw_text, quote, weight, matched_confidence)
        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
        ON CONFLICT (source, source_id) DO NOTHING
        RETURNING id, kind, source, company_id
        """,
        company_id,
        kind,
        source,
        source_id,
        observed_at,
        raw_text,
        quote,
        weight,
        matched_confidence,
    )


async def collector_health(days: int = 7) -> list[dict]:
    """Per-source counts for the recent window.

    A source that has dropped to zero is the failure this system is most likely
    to hide: a broken scraper looks exactly like a quiet week.
    """
    return await db.fetch(
        """
        SELECT source,
               count(*) FILTER (WHERE observed_at >= now() - make_interval(days => $1)) AS recent,
               count(*) AS total,
               max(observed_at) AS last_seen
        FROM signals
        GROUP BY source
        ORDER BY recent ASC, source
        """,
        days,
    )
