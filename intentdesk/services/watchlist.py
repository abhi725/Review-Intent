from intentdesk import db

DEFAULT_SOURCES = ["tech", "jobs", "g2", "capterra", "reddit", "vendor_news"]


async def list_all(active_only: bool = False) -> list[dict]:
    """Competitors tracked, with what each one has actually produced."""
    return await db.fetch(
        """
        SELECT w.id, w.competitor, w.sources, w.active,
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


async def add(competitor: str, sources: list[str] | None = None) -> dict:
    return await db.fetchrow(
        """
        INSERT INTO watchlist (competitor, sources) VALUES ($1, $2::jsonb)
        ON CONFLICT (competitor) DO UPDATE SET sources = EXCLUDED.sources, active = true
        RETURNING *
        """,
        competitor,
        sources or DEFAULT_SOURCES,
    )


async def remove(competitor: str) -> bool:
    """Deactivate rather than delete — the companies and signals it produced
    stay meaningful."""
    result = await db.execute(
        "UPDATE watchlist SET active = false WHERE competitor = $1", competitor
    )
    return result.endswith("1")
