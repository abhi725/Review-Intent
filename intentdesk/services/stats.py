from datetime import date

from intentdesk import db
from intentdesk.config import settings
from intentdesk.services import preferences


async def overview() -> dict:
    """The KPI strip, plus the numbers that tell us whether this whole channel
    is worth running: how many detected companies ever become contactable.

    Contactability is counted per channel rather than as a single number.
    Reporting only email reachability made the funnel look dead on Apollo's free
    plan, which returns a company phone and never an address — the leads were
    reachable, the metric just could not see it.
    """
    row = await db.fetchrow(
        """
        SELECT
          (SELECT count(*) FROM companies)                                     AS install_base,
          (SELECT count(*) FROM companies WHERE vendor_verified)               AS vendor_verified,
          (SELECT count(*) FROM companies WHERE enriched_at IS NOT NULL)       AS enriched,
          (SELECT count(*) FROM leads)                                         AS leads_total,
          (SELECT count(*) FROM leads WHERE status = 'NEW')                    AS awaiting,
          (SELECT count(*) FROM leads WHERE heat = 'hot')                      AS hot,
          (SELECT count(*) FROM leads
             WHERE status = 'APPROVED'
               AND status_changed_at >= now() - interval '7 days')             AS approved_7d,
          (SELECT count(*) FROM leads WHERE created_at >= current_date)        AS new_today,
          (SELECT count(*) FROM leads l JOIN companies c ON c.id = l.company_id
             WHERE l.contact_phone IS NOT NULL OR c.phone IS NOT NULL)         AS reachable_phone,
          (SELECT count(*) FROM leads WHERE contact_email IS NOT NULL)         AS reachable_email,
          (SELECT count(*) FROM leads
             WHERE draft_body IS NOT NULL AND draft_body <> '')                AS drafted,
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

    prefs = await preferences.all_prefs()
    channel = str(prefs["outreach_channel"])

    install_base = row["install_base"] or 0
    by_channel = {
        "phone": row["reachable_phone"] or 0,
        "email": row["reachable_email"] or 0,
    }
    by_channel["both"] = max(by_channel["phone"], by_channel["email"])
    contactable = by_channel.get(channel, by_channel["both"])

    def pct(n: int) -> float:
        return round(100 * n / install_base, 1) if install_base else 0.0

    return {
        **row,
        "contactable": contactable,
        "contactable_pct": pct(contactable),
        "reachable_phone_pct": pct(by_channel["phone"]),
        "reachable_email_pct": pct(by_channel["email"]),
        # Kept under its old name so nothing downstream breaks; it now answers
        # "reachable on the channel we actually work" instead of "has an email".
        "identifiable_pct": pct(contactable),
        "outreach_channel": channel,
        "generic_pitch": await preferences.value_proposition_is_default(),
        "spend_month_usd": float(spent or 0),
        "spend_cap_usd": float(prefs["monthly_spend_cap_usd"] or settings.monthly_spend_cap_usd),
        "month": date.today().strftime("%Y-%m"),
    }
