import json
from datetime import datetime
from typing import Optional

from intentdesk import db

KINDS = ("install", "job_post", "review", "forum", "vendor_news")


async def list_signals(
    kind: Optional[str] = None,
    matched: Optional[bool] = None,
    since: Optional[datetime] = None,
    limit: int = 100,
    platform: Optional[str] = None,
    source_site: Optional[str] = None,
    rating_lte: Optional[float] = None,
    country: Optional[str] = None,
    category: Optional[str] = None,
    until: Optional[datetime] = None,
    switched_only: bool = False,
) -> list[dict]:
    """The signal feed. `matched=False` returns signals we could not tie to a
    tracked company — they still matter, they prove the collector is alive.

    The filter set mirrors the feed's three-level selector: competitor
    (`platform`) → review site (`source_site`) → everything else.
    """
    return await db.fetch(
        """
        SELECT s.id, s.kind, s.source, s.observed_at, s.quote, s.weight,
               s.matched_confidence, s.company_id,
               s.url, s.author, s.author_role, s.rating, s.raw_text,
               s.platform, s.source_site, s.country, s.region,
               s.switched_from, s.switched_reason, s.subscores,
               s.category, s.core_complaint, s.severity, s.fetched_at,
               c.name AS company, c.domain
        FROM signals s
        LEFT JOIN companies c ON c.id = s.company_id
        WHERE ($1::text IS NULL OR s.kind = $1)
          AND ($2::bool IS NULL
               OR ($2 IS TRUE AND s.company_id IS NOT NULL)
               OR ($2 IS FALSE AND s.company_id IS NULL))
          AND ($3::timestamptz IS NULL OR s.observed_at >= $3)
          AND ($5::text IS NULL OR s.platform = $5)
          AND ($6::text IS NULL OR s.source_site = $6)
          -- A row with no rating is not "rated well"; it is unrated, and a
          -- rating filter must not silently sweep it in.
          AND ($7::real IS NULL OR (s.rating IS NOT NULL AND s.rating <= $7))
          AND ($8::text IS NULL OR s.country = $8)
          AND ($9::text IS NULL OR s.category = $9)
          AND ($10::timestamptz IS NULL OR s.observed_at <= $10)
          AND (NOT $11::bool OR s.switched_from IS NOT NULL)
        ORDER BY s.observed_at DESC
        LIMIT $4
        """,
        kind,
        matched,
        since,
        min(limit, 500),
        platform,
        source_site,
        rating_lte,
        country,
        category,
        until,
        switched_only,
    )


async def feed_facets() -> dict:
    """What the selector should offer, derived from what is actually stored.

    Built from the data rather than from the watchlist so the dropdowns can
    never offer a competitor with nothing behind it — an empty result that
    looks like a bug rather than an honest absence.
    """
    rows = await db.fetch(
        """
        SELECT coalesce(platform, 'unknown') AS platform,
               coalesce(source_site, source) AS source_site,
               count(*) AS n,
               count(*) FILTER (WHERE rating IS NOT NULL AND rating <= 3) AS negative
        FROM signals
        GROUP BY 1, 2
        ORDER BY n DESC
        """
    )
    return {
        "pairs": [dict(r) for r in rows],
        "platforms": sorted({r["platform"] for r in rows}),
        "sites": sorted({r["source_site"] for r in rows}),
    }


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
    url: Optional[str] = None,
    author: Optional[str] = None,
    author_role: Optional[str] = None,
    rating: Optional[float] = None,
    platform: Optional[str] = None,
    source_site: Optional[str] = None,
    country: Optional[str] = None,
    region: Optional[str] = None,
    switched_from: Optional[str] = None,
    switched_reason: Optional[str] = None,
    subscores: Optional[dict] = None,
) -> Optional[dict]:
    """Store a signal, ignoring one we have already seen.

    Dedup is on (source, source_id) so a rescan of the same G2 page cannot
    re-score a company or trigger a second draft.

    The provenance arguments default to None because most sources supply none of
    them and every existing caller predates them.

    `category`, `core_complaint` and `severity` are deliberately absent here:
    they come from an LLM pass over the stored text, not from the collector, and
    are written later by `classify()`.
    """
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {KINDS}, got {kind!r}")

    return await db.fetchrow(
        """
        INSERT INTO signals (company_id, kind, source, source_id, observed_at,
                             raw_text, quote, weight, matched_confidence,
                             url, author, author_role, rating,
                             platform, source_site, country, region,
                             switched_from, switched_reason, subscores,
                             fetched_at)
        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,
                $14,$15,$16,$17,$18,$19,$20, now())
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
        url,
        author,
        author_role,
        rating,
        platform,
        # Falls back to `source` so rows written by collectors that predate the
        # column still group correctly in the feed instead of landing in a
        # nameless "unknown site" bucket.
        source_site or source,
        country,
        region,
        switched_from,
        switched_reason,
        json.dumps(subscores) if subscores else None,
    )


async def update_provenance(
    source: str,
    source_id: str,
    **fields,
) -> Optional[dict]:
    """Fill in provenance on a signal that is already stored.

    `record()` is ON CONFLICT DO NOTHING, which is right for collection — a
    rescan must never re-score a company or trigger a second draft. But it means
    a *fixed* field mapping cannot be replayed over rows collected under the
    broken one, and those rows are exactly the ones missing platform, country
    and sub-scores.

    Only writes columns that are currently NULL, so this can never overwrite
    something a later, better source established.
    """
    allowed = ("platform", "source_site", "country", "region",
               "switched_from", "switched_reason", "subscores",
               "url", "author", "rating")
    sets, args = [], [source, source_id]
    for key in allowed:
        if key not in fields or fields[key] is None:
            continue
        value = json.dumps(fields[key]) if key == "subscores" else fields[key]
        args.append(value)
        sets.append(f"{key} = coalesce({key}, ${len(args)})")

    if not sets:
        return None

    return await db.fetchrow(
        f"UPDATE signals SET {', '.join(sets)} "
        "WHERE source = $1 AND source_id = $2 "
        "RETURNING id, platform, source_site",
        *args,
    )


async def classify(signal_id: int, category: str, core_complaint: str,
                   severity: int) -> None:
    """Persist the LLM's reading of a review.

    Stored rather than recomputed: re-running an LLM over the same review every
    time a screen is drawn is both slow and billable.
    """
    await db.execute(
        "UPDATE signals SET category = $2, core_complaint = $3, severity = $4 "
        "WHERE id = $1",
        signal_id, category, core_complaint, severity,
    )


async def counts(days: int = 30) -> dict:
    """Totals for the feed header: how much came in, how much we could tie to a
    company, and the split by kind.

    One grouped query rather than one per kind. The per-kind numbers are what
    make "total reviews" answerable at a glance; the matched split is what makes
    a broken matcher visible before it quietly starves the queue.
    """
    rows = await db.fetch(
        """
        SELECT kind,
               count(*)                                   AS total,
               count(*) FILTER (WHERE company_id IS NOT NULL) AS matched,
               avg(rating) FILTER (WHERE rating IS NOT NULL)  AS avg_rating
        FROM signals
        WHERE observed_at >= now() - make_interval(days => $1)
        GROUP BY kind
        """,
        days,
    )

    by_kind = {
        r["kind"]: {
            "total": int(r["total"]),
            "matched": int(r["matched"]),
            "avg_rating": round(float(r["avg_rating"]), 2) if r["avg_rating"] is not None else None,
        }
        for r in rows
    }
    # Every kind present, including the ones with nothing in them. A missing key
    # would render as a gap in the strip, which reads as "no data yet" rather
    # than the "zero, and that is the news" it usually means.
    for kind in KINDS:
        by_kind.setdefault(kind, {"total": 0, "matched": 0, "avg_rating": None})

    return {
        "days": days,
        "total": sum(k["total"] for k in by_kind.values()),
        "matched": sum(k["matched"] for k in by_kind.values()),
        "by_kind": by_kind,
    }


async def for_export(
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
    platform: Optional[str] = None,
    source_site: Optional[str] = None,
    rating_lte: Optional[float] = None,
    group: str = "month",
    limit: int = 20_000,
) -> list[dict]:
    """Stored reviews for the period export, one row each, newest first.

    **Reads only.** Export never triggers a collection: a careless date range on
    a paid source would otherwise turn a download into a bill, and the person
    picking dates has no way to know which months are already cached.

    `group` adds a pre-formatted period label rather than leaving the caller to
    derive one — Postgres knows the row's timezone and a spreadsheet formula
    does not, so a review at 23:40 on the 31st must not land in the wrong month
    depending on who opens the file.
    """
    if group not in ("month", "year"):
        raise ValueError(f"group must be 'month' or 'year', got {group!r}")

    fmt = "YYYY-MM" if group == "month" else "YYYY"

    return await db.fetch(
        f"""
        SELECT to_char(s.observed_at, '{fmt}') AS period,
               s.observed_at, s.platform, s.source_site, s.source,
               s.rating, s.author, s.author_role, s.country, s.region,
               s.category, s.core_complaint, s.severity,
               s.switched_from, s.switched_reason,
               s.quote, s.raw_text, s.url,
               c.name AS company, c.domain,
               ri.full_name AS reviewer_name, ri.title AS reviewer_title,
               ri.company_name AS reviewer_company, ri.confidence AS reviewer_confidence
        FROM signals s
        LEFT JOIN companies c ON c.id = s.company_id
        LEFT JOIN reviewer_identity ri ON ri.signal_id = s.id
        WHERE s.kind IN ('review', 'forum')
          AND ($1::timestamptz IS NULL OR s.observed_at >= $1)
          AND ($2::timestamptz IS NULL OR s.observed_at <= $2)
          AND ($3::text IS NULL OR s.platform = $3)
          AND ($4::text IS NULL OR s.source_site = $4)
          AND ($5::real IS NULL OR (s.rating IS NOT NULL AND s.rating <= $5))
        ORDER BY s.observed_at DESC
        LIMIT $6
        """,
        since, until, platform, source_site, rating_lte, max(int(limit), 1),
    )


async def period_summary(
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
    platform: Optional[str] = None,
    source_site: Optional[str] = None,
    rating_lte: Optional[float] = None,
    group: str = "month",
) -> list[dict]:
    """Per-period totals for the export's summary sheet.

    Aggregated in Postgres rather than in Python over the exported rows: the row
    export is capped, and a summary computed from a truncated page would quietly
    disagree with itself.
    """
    if group not in ("month", "year"):
        raise ValueError(f"group must be 'month' or 'year', got {group!r}")

    fmt = "YYYY-MM" if group == "month" else "YYYY"

    return await db.fetch(
        f"""
        SELECT to_char(s.observed_at, '{fmt}') AS period,
               COALESCE(s.platform, 'unknown')            AS platform,
               COALESCE(s.source_site, s.source)          AS source_site,
               count(*)                                   AS reviews,
               avg(s.rating) FILTER (WHERE s.rating IS NOT NULL) AS avg_rating,
               count(*) FILTER (WHERE s.rating IS NOT NULL AND s.rating <= 2) AS one_or_two_star,
               count(*) FILTER (WHERE s.switched_from IS NOT NULL) AS switched,
               count(*) FILTER (WHERE s.company_id IS NOT NULL)    AS matched,
               mode() WITHIN GROUP (ORDER BY s.category)  AS top_category
        FROM signals s
        WHERE s.kind IN ('review', 'forum')
          AND ($1::timestamptz IS NULL OR s.observed_at >= $1)
          AND ($2::timestamptz IS NULL OR s.observed_at <= $2)
          AND ($3::text IS NULL OR s.platform = $3)
          AND ($4::text IS NULL OR s.source_site = $4)
          AND ($5::real IS NULL OR (s.rating IS NOT NULL AND s.rating <= $5))
        GROUP BY 1, 2, 3
        ORDER BY 1 DESC, reviews DESC
        """,
        since, until, platform, source_site, rating_lte,
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
