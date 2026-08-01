from datetime import date

from intentdesk import db
from intentdesk.config import settings


async def overview() -> dict:
    """The KPI strip, plus the numbers that tell us whether this whole channel
    is worth running: how many detected companies ever become contactable."""
    row = await db.fetchrow(
        """
        SELECT
          (SELECT count(*) FROM companies)                                     AS install_base,
          (SELECT count(*) FROM leads)                                         AS leads_total,
          (SELECT count(*) FROM leads WHERE status = 'NEW')                    AS awaiting,
          (SELECT count(*) FROM leads WHERE heat = 'hot')                      AS hot,
          (SELECT count(*) FROM leads
             WHERE status = 'APPROVED'
               AND status_changed_at >= now() - interval '7 days')             AS approved_7d,
          (SELECT count(*) FROM leads WHERE created_at >= current_date)        AS new_today,
          (SELECT count(*) FROM leads WHERE contact_email IS NOT NULL)         AS contactable,
          (SELECT count(*) FROM signals
             WHERE observed_at >= now() - interval '7 days')                   AS signals_7d,
          (SELECT count(*) FROM signals
             WHERE company_id IS NULL
               AND observed_at >= now() - interval '7 days')                   AS unmatched_7d,
          (SELECT count(*) FROM suppression)                                   AS suppressed
        """
    )

    spent = await db.fetchval(
        """
        SELECT COALESCE(sum(amount_usd), 0) FROM spend
        WHERE day >= date_trunc('month', current_date)
        """
    )

    install_base = row["install_base"] or 0
    contactable = row["contactable"] or 0

    return {
        **row,
        "identifiable_pct": round(100 * contactable / install_base, 1) if install_base else 0.0,
        "spend_month_usd": float(spent or 0),
        "spend_cap_usd": settings.monthly_spend_cap_usd,
        "month": date.today().strftime("%Y-%m"),
    }
