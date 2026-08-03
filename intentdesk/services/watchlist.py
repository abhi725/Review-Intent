from intentdesk import db

DEFAULT_SOURCES = ["tech", "jobs", "g2", "capterra", "reddit", "vendor_news"]


async def list_all(active_only: bool = False) -> list[dict]:
    """Competitors tracked, with what each one has actually produced."""
    return await db.fetch(
        """
        SELECT w.id, w.competitor, w.sources, w.active,
               w.segment, w.trustpilot_url, w.g2_slug,
               COALESCE(c.companies, 0) AS install_base,
               COALESCE(n.negatives, 0) AS negatives_180d,
               COALESCE(l.leads, 0)     AS leads_produced
        FROM watchlist w
        LEFT JOIN (
            SELECT vendor, count(*) AS companies FROM companies GROUP BY vendor
        ) c ON c.vendor = w.competitor
        LEFT JOIN (
            SELECT co.vendor, count(*) AS negatives
            FROM signals s JOIN companies co ON co.id = s.company_id
            WHERE s.kind = 'review' AND s.observed_at >= now() - interval '180 days'
            GROUP BY co.vendor
        ) n ON n.vendor = w.competitor
        LEFT JOIN (
            SELECT co.vendor, count(*) AS leads
            FROM leads le JOIN companies co ON co.id = le.company_id
            GROUP BY co.vendor
        ) l ON l.vendor = w.competitor
        WHERE ($1::bool IS FALSE OR w.active IS TRUE)
        ORDER BY install_base DESC, w.competitor
        """,
        active_only,
    )


async def add(
    competitor: str,
    sources: list[str] | None = None,
    *,
    segment: str | None = None,
    trustpilot_url: str | None = None,
    g2_slug: str | None = None,
    active: bool = True,
) -> dict:
    """Add or update a tracked competitor.

    `active` is a real parameter rather than always true: the Phase C expansion
    brands are registered so their segment and slugs are recorded, but switching
    them on multiplies what every paid run costs, so that is a separate decision.

    The verified-page columns use COALESCE so an existing hand-entered URL is
    never wiped by a re-seed that happens not to carry one — the same failure that
    once erased a Tabbly agent prompt.
    """
    return await db.fetchrow(
        """
        INSERT INTO watchlist (competitor, sources, active, segment,
                               trustpilot_url, g2_slug)
        VALUES ($1, $2::jsonb, $3, $4, $5, $6)
        ON CONFLICT (competitor) DO UPDATE SET
            sources        = EXCLUDED.sources,
            active         = EXCLUDED.active,
            segment        = COALESCE(EXCLUDED.segment, watchlist.segment),
            trustpilot_url = COALESCE(EXCLUDED.trustpilot_url, watchlist.trustpilot_url),
            g2_slug        = COALESCE(EXCLUDED.g2_slug, watchlist.g2_slug)
        RETURNING *
        """,
        competitor,
        sources or DEFAULT_SOURCES,
        active,
        segment,
        trustpilot_url,
        g2_slug,
    )


async def remove(competitor: str) -> bool:
    """Deactivate rather than delete — the companies and signals it produced
    stay meaningful."""
    result = await db.execute(
        "UPDATE watchlist SET active = false WHERE competitor = $1", competitor
    )
    return result.endswith("1")
