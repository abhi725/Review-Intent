"""Does this thing still work?

Two failures are invisible from the dashboard, and both look exactly like a
quiet week:

1. A collector that has silently stopped returning anything — a scraper the
   provider blocked, or credentials that expired.
2. A cron that has stopped firing altogether, which is worse, because even
   `collector_health` looks unchanged when nothing is writing to it.

`alerts()` names both. Everything here is derived from what is already in the
database, so it costs nothing to call and cannot itself drift out of date.
"""

from datetime import datetime, timedelta, timezone

from intentdesk import db
from intentdesk.collectors import availability

# A collector that produced signals before and none since is a regression. One
# that has never produced anything was never working, which is a different
# problem and belongs in `scan_status`, not in alerts.
QUIET_DAYS = 10

# Weekly cron plus slack. Alerting at 8 days would page on an ordinary run that
# happened to slip a day.
SCAN_OVERDUE_DAYS = 10

SEVERITY_ORDER = {"critical": 0, "warning": 1, "info": 2}


async def alerts() -> list[dict]:
    """Everything currently wrong, worst first. Empty list means healthy."""
    out: list[dict] = []
    now = datetime.now(timezone.utc)

    # ---- has the scan run at all? ----
    last_scan = await db.fetchrow(
        "SELECT started_at, ok, detail FROM job_runs WHERE job = 'scan' "
        "ORDER BY started_at DESC LIMIT 1"
    )
    if last_scan is None:
        out.append({
            "severity": "warning",
            "code": "scan_never_ran",
            "message": "No scan has ever been recorded. The cron is not wired up yet.",
        })
    else:
        age = (now - last_scan["started_at"]).days
        if age >= SCAN_OVERDUE_DAYS:
            out.append({
                "severity": "critical",
                "code": "scan_overdue",
                "message": f"Last scan was {age} days ago. The cron has stopped firing.",
            })
        elif not last_scan["ok"]:
            errors = (last_scan["detail"] or {}).get("errors") or []
            out.append({
                "severity": "warning",
                "code": "scan_errors",
                "message": f"The last scan reported {len(errors)} collector error(s).",
                "detail": errors[:5],
            })

    # ---- collectors that used to work and stopped ----
    rows = await db.fetch(
        """
        SELECT source, max(observed_at) AS last_seen, count(*) AS total
        FROM signals GROUP BY source
        """
    )
    for row in rows:
        quiet_for = (now - row["last_seen"]).days
        if quiet_for >= QUIET_DAYS:
            out.append({
                "severity": "warning",
                "code": "collector_quiet",
                "message": (
                    f"{row['source']} has returned nothing for {quiet_for} days "
                    f"after {row['total']} signals. A blocked scraper looks like this."
                ),
            })

    # ---- credentials that were there and are not ----
    for coll in availability():
        if not coll["available"] and coll["missing"]:
            out.append({
                "severity": "info",
                "code": "collector_unconfigured",
                "message": f"{coll['name']} is waiting on {', '.join(coll['missing'])}.",
            })

    # ---- spend ----
    spend = await db.fetchrow(
        """
        SELECT COALESCE(sum(amount_usd), 0) AS spent
        FROM spend WHERE day >= date_trunc('month', current_date)
        """
    )
    cap = float(
        (await db.fetchval("SELECT value FROM settings WHERE key = 'monthly_spend_cap_usd'"))
        or 0
    )
    if cap and float(spend["spent"]) >= cap:
        out.append({
            "severity": "critical",
            "code": "spend_cap_reached",
            "message": (
                f"${float(spend['spent']):.2f} of ${cap:.2f} spent this month. "
                "Paid collectors will be skipped until the month rolls over."
            ),
        })

    out.sort(key=lambda a: SEVERITY_ORDER.get(a["severity"], 9))
    return out


async def digest(days: int = 7) -> dict:
    """What happened since the last digest, in the shape a morning message wants.

    Deliberately includes the bad news. A digest that only lists new leads
    trains the reader to skim it, and the week it matters is the week it is
    empty for the wrong reason.
    """
    since = datetime.now(timezone.utc) - timedelta(days=days)

    counts = await db.fetchrow(
        """
        SELECT
          (SELECT count(*) FROM leads WHERE created_at >= $1)                  AS new_leads,
          (SELECT count(*) FROM leads WHERE created_at >= $1 AND heat = 'hot') AS new_hot,
          (SELECT count(*) FROM leads WHERE status = 'NEW')                    AS awaiting,
          (SELECT count(*) FROM signals WHERE observed_at >= $1)               AS new_signals,
          (SELECT count(*) FROM leads
             WHERE status = 'APPROVED' AND status_changed_at >= $1)            AS approved,
          (SELECT COALESCE(sum(amount_usd), 0) FROM spend
             WHERE day >= date_trunc('month', current_date))                   AS spend_month
        """,
        since,
    )

    top = await db.fetch(
        """
        SELECT l.id, l.score, l.heat, c.name AS company, c.city, c.vendor,
               COALESCE(l.contact_phone, c.phone) AS phone
        FROM leads l JOIN companies c ON c.id = l.company_id
        WHERE l.status = 'NEW' AND l.created_at >= $1
        ORDER BY l.score DESC LIMIT 10
        """,
        since,
    )

    current = await alerts()
    result = {
        "window_days": days,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        **{k: (float(v) if k == "spend_month" else v) for k, v in counts.items()},
        "top_new_leads": top,
        "alerts": current,
        "healthy": not any(a["severity"] == "critical" for a in current),
    }

    await db.execute(
        """
        INSERT INTO job_runs (job, started_at, finished_at, ok, detail)
        VALUES ('digest', now(), now(), $1, $2::jsonb)
        """,
        result["healthy"],
        {"new_leads": counts["new_leads"], "alerts": len(current)},
    )
    return result


def render_digest(data: dict) -> str:
    """Plain text, for Slack or email. No formatting a mail client can mangle."""
    lines = [
        f"Intent Desk — last {data['window_days']} days",
        "",
        f"{data['new_leads']} new leads ({data['new_hot']} hot), "
        f"{data['awaiting']} awaiting review",
        f"{data['new_signals']} signals collected, "
        f"{data['approved']} approved",
        f"${data['spend_month']:.2f} spent this month",
    ]

    if data["top_new_leads"]:
        lines += ["", "Top new leads:"]
        for lead in data["top_new_leads"]:
            where = lead["city"] or "location unknown"
            reach = lead["phone"] or "no number yet"
            lines.append(
                f"  {lead['score']:>3}  {lead['company']} — {where} — "
                f"runs {lead['vendor']} — {reach}"
            )

    if data["alerts"]:
        lines += ["", "Needs attention:"]
        for alert in data["alerts"]:
            lines.append(f"  [{alert['severity']}] {alert['message']}")
    else:
        lines += ["", "No alerts."]

    return "\n".join(lines)


async def reconcile_spend() -> dict:
    """Compare recorded spend against Apify's own monthly usage.

    The numbers drift for a reason worth knowing: a run that times out or fails
    still bills, and this system only records cost on a run it saw finish. When
    Apify's figure is the higher one, the cap is being enforced against an
    understatement — which is exactly the direction that overspends.
    """
    from intentdesk.config import settings

    recorded = float(await db.fetchval(
        "SELECT COALESCE(sum(amount_usd), 0) FROM spend "
        "WHERE day >= date_trunc('month', current_date)"
    ) or 0)

    if not settings.apify_token:
        return {"recorded_usd": recorded, "provider_usd": None,
                "error": "APIFY_TOKEN is not set"}

    import httpx

    try:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.get(
                "https://api.apify.com/v2/users/me/usage/monthly",
                headers={"Authorization": f"Bearer {settings.apify_token}"},
            )
            response.raise_for_status()
            data = (response.json() or {}).get("data") or {}
    except Exception as exc:
        return {"recorded_usd": recorded, "provider_usd": None,
                "error": f"{type(exc).__name__}: {exc}"}

    provider = float(data.get("totalUsageCreditsUsdAfterVolumeDiscount")
                     or data.get("totalUsageCreditsUsd") or 0)
    drift = round(provider - recorded, 4)

    await db.execute(
        """
        INSERT INTO job_runs (job, started_at, finished_at, ok, detail)
        VALUES ('reconcile', now(), now(), TRUE, $1::jsonb)
        """,
        {"recorded_usd": recorded, "provider_usd": provider, "drift_usd": drift},
    )

    return {
        "recorded_usd": round(recorded, 4),
        "provider_usd": round(provider, 4),
        "drift_usd": drift,
        "understated": drift > 0.01,
    }
