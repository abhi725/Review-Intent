"""The scan: collect, match, score, and rebuild the queue.

Runs from the dashboard button, the n8n cron, and later the MCP `scan` tool.
Rescoring works even with no collectors wired up, so the ranking rules can be
changed and applied to signals already in the database.
"""

from datetime import datetime, timezone

from intentdesk import db
from intentdesk.collectors import availability, registry
from intentdesk.config import settings
from intentdesk.services import companies, leads, matching, scoring, signals


async def rescore_all() -> dict:
    """Recompute every company's score and refresh its live lead.

    Suppressed companies are skipped rather than scored — a rejected company
    must not quietly reappear at the top of the queue after the next scan.
    """
    rows = await db.fetch(
        """
        SELECT c.id, c.domain, c.agents_est,
               COALESCE(json_agg(json_build_object(
                   'kind', s.kind, 'source', s.source, 'observed_at', s.observed_at)
               ) FILTER (WHERE s.id IS NOT NULL), '[]'::json) AS sigs
        FROM companies c
        LEFT JOIN signals s ON s.company_id = c.id
        WHERE NOT EXISTS (SELECT 1 FROM suppression x WHERE x.domain = c.domain)
        GROUP BY c.id
        """
    )

    band = (settings.target_agents_min, settings.target_agents_max)
    now = datetime.now(timezone.utc)
    scored = created = 0

    for row in rows:
        sigs = [
            {**s, "observed_at": datetime.fromisoformat(s["observed_at"])}
            for s in row["sigs"]
        ]
        if not sigs:
            continue
        score = scoring.score_company(sigs, row["agents_est"], band, now)
        before = await db.fetchval(
            "SELECT count(*) FROM leads WHERE company_id = $1 AND status = ANY($2::text[])",
            row["id"],
            list(leads.LIVE_STATUSES),
        )
        await leads.upsert_lead(row["id"], score)
        scored += 1
        if not before:
            created += 1

    return {"companies_scored": scored, "leads_created": created}


async def run(competitor: str | None = None) -> dict:
    """Full scan. Returns a summary honest enough to debug from."""
    started = datetime.now(timezone.utc)

    targets = [competitor] if competitor else [
        w["competitor"] for w in await db.fetch(
            "SELECT competitor FROM watchlist WHERE active IS TRUE ORDER BY competitor"
        )
    ]

    collected = 0
    stored = 0
    unmatched = 0
    per_collector: list[dict] = []
    skipped: list[dict] = []

    for coll in registry():
        if not coll.available():
            skipped.append({
                "collector": coll.name,
                "reason": "missing credentials: " + ", ".join(coll.missing_credentials())
                if coll.missing_credentials() else "not implemented yet",
            })
            continue

        got = new = 0
        errors: list[str] = []
        for target in targets:
            try:
                raw = await coll.collect(target)
            except Exception as exc:
                errors.append(f"{target}: {type(exc).__name__}: {exc}")
                continue

            got += len(raw)
            for r in raw:
                company_id, confidence = await matching.resolve(
                    r.company_name, r.company_domain
                )
                if company_id is None and r.company_domain:
                    company = await companies.upsert(
                        name=r.company_name or r.company_domain,
                        domain=r.company_domain,
                        vendor=r.vendor or target,
                        city=r.city,
                        agents_est=r.agents_est,
                    )
                    company_id, confidence = company["id"], 1.0

                if company_id is None:
                    unmatched += 1

                inserted = await signals.record(
                    kind=r.kind, source=r.source, source_id=r.source_id,
                    observed_at=r.observed_at, company_id=company_id,
                    raw_text=r.raw_text, quote=r.quote,
                    weight=scoring.WEIGHTS.get(r.kind, 0),
                    matched_confidence=confidence,
                )
                if inserted:
                    new += 1

        collected += got
        stored += new
        per_collector.append(
            {"collector": coll.name, "found": got, "new": new, "errors": errors}
        )

    rescore = await rescore_all()

    return {
        "started_at": started.isoformat(),
        "seconds": round((datetime.now(timezone.utc) - started).total_seconds(), 2),
        "competitors": targets,
        "signals_found": collected,
        "signals_new": stored,
        "signals_unmatched": unmatched,
        "collectors_ran": per_collector,
        "collectors_skipped": skipped,
        **rescore,
    }


async def status() -> dict:
    """What is wired up and what is still waiting on a token."""
    avail = availability()
    return {
        "collectors": avail,
        "ready": sum(1 for a in avail if a["available"]),
        "total": len(avail),
    }
