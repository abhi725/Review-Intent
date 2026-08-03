"""The scan: collect, match, score, and rebuild the queue.

Runs from the dashboard button, the n8n cron, and later the MCP `scan` tool.
Rescoring works even with no collectors wired up, so the ranking rules can be
changed and applied to signals already in the database.
"""

from datetime import datetime, timezone

from intentdesk import db
from intentdesk.collectors import PRICED_ACTION, RETIRED, availability, registry
from intentdesk.services import (
    companies,
    leads,
    matching,
    preferences,
    scoring,
    signals,
    spend,
)


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

    band = await preferences.agent_band()
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


async def run(
    competitor: str | None = None,
    free_only: bool = False,
    sources: list[str] | None = None,
    actor_email: str | None = None,
) -> dict:
    """Full scan. Returns a summary honest enough to debug from.

    `free_only` runs the collectors that cost nothing. It exists because the
    first run of a new collector is also its first test, and being able to
    exercise the orchestration — matching, scoring, the queue rebuild — without
    committing budget is what makes that test cheap to repeat. **Every scheduled
    entry point passes it**: paid work belongs on a click with the price on it,
    not on a cron that bills quietly at 3am.

    `sources` narrows the run to named collectors, which is what the per-source
    buttons in the Sources panel post to. Omitted means all of them.
    """
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

    # Providers bill as a run proceeds, so a code-side cap cannot stop one
    # mid-flight. What it can do is refuse to start another when the month is
    # already spent — the account-level limit remains the real backstop.
    prefs = await preferences.all_prefs()
    cap = float(prefs["monthly_spend_cap_usd"])
    spent = float(await db.fetchval(
        "SELECT COALESCE(sum(amount_usd),0) FROM spend WHERE day >= date_trunc('month', current_date)"
    ) or 0)
    budget_exhausted = spent >= cap

    for coll in registry():
        if sources and coll.name not in sources:
            continue

        # `cost_model`, not `requires`. The old test was "needs a credential",
        # which is wrong in both directions: a source can need a key and still be
        # free, so a free-only run was skipping a free source, and any future
        # paid source without a token would have slipped through as free.
        paid = coll.cost_model != "free"

        if free_only and paid:
            skipped.append({
                "collector": coll.name,
                "reason": f"free-only run; {coll.name} bills {coll.cost_model}",
            })
            continue

        # A paid collector on a scheduled cadence is a contradiction — it would
        # mean unattended spending — so it is refused here rather than trusted to
        # be configured correctly.
        if paid and coll.cadence == "scheduled":
            skipped.append({
                "collector": coll.name,
                "reason": (f"{coll.name} is marked scheduled but bills "
                           f"{coll.cost_model}; paid collectors must be on_demand"),
            })
            continue

        if budget_exhausted and paid:
            skipped.append({
                "collector": coll.name,
                "reason": f"monthly spend cap reached (${spent:.2f} of ${cap:.2f})",
            })
            continue

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
                    url=r.url, author=r.author,
                    author_role=r.author_role, rating=r.rating,
                    # Everything a collector now returns has to be forwarded
                    # here explicitly. This call is the narrow point the whole
                    # pipeline passes through: a field the collector sets and
                    # this line forgets is silently dropped, and looks exactly
                    # like a source that never supplied it.
                    platform=r.platform or r.vendor or target,
                    source_site=r.source_site or r.source,
                    country=r.country, region=r.region,
                    switched_from=r.switched_from,
                    switched_reason=r.switched_reason,
                    subscores=r.subscores,
                )
                if inserted:
                    new += 1

        cost = float(getattr(coll, "last_cost_usd", 0) or 0)
        if cost:
            action = PRICED_ACTION.get(coll.name, f"collect_{coll.name}")
            await spend.record(
                coll.name, cost,
                action=action,
                units=max(got, 1),
                estimated_usd=spend.estimate(action, max(got, 1))["estimated_usd"],
                competitor=competitor,
                actor_email=actor_email,
                detail={"targets": targets, "found": got, "new": new},
            )

        collected += got
        stored += new
        # A collector that declined every target is neither a success nor a
        # failure, and reporting it as "found 0" makes a permanent refusal look
        # like a quiet week. Trustpilot does this per brand.
        skip_reason = getattr(coll, "last_skip_reason", None)
        if skip_reason and got == 0:
            skipped.append({"collector": coll.name, "reason": skip_reason})

        per_collector.append(
            {"collector": coll.name, "found": got, "new": new,
             "cost_usd": round(cost, 4), "errors": errors,
             "declined": skip_reason}
        )

    rescore = await rescore_all()

    summary = {
        "started_at": started.isoformat(),
        "seconds": round((datetime.now(timezone.utc) - started).total_seconds(), 2),
        "competitors": targets,
        "sources": sources or "all",
        "free_only": free_only,
        "signals_found": collected,
        "signals_new": stored,
        "signals_unmatched": unmatched,
        "collectors_ran": per_collector,
        "collectors_skipped": skipped,
        **rescore,
    }

    # A scan that ran and found nothing and a scan that never ran look identical
    # from the queue. Recording every run is what lets the digest tell them apart.
    await db.execute(
        """
        INSERT INTO job_runs (job, started_at, finished_at, ok, detail)
        VALUES ('scan', $1, now(), $2, $3::jsonb)
        """,
        started,
        not any(c["errors"] for c in per_collector),
        {
            "signals_new": stored,
            "collectors_ran": [c["collector"] for c in per_collector],
            "errors": [e for c in per_collector for e in c["errors"]][:10],
            "cost_usd": round(sum(c["cost_usd"] for c in per_collector), 4),
        },
    )

    return summary


async def status() -> dict:
    """What is wired up and what is still waiting on a token."""
    avail = availability()
    return {
        "collectors": avail,
        "ready": sum(1 for a in avail if a["available"]),
        "total": len(avail),
        # What the cron will actually touch. Shown because "scan ran" and "scan
        # ran the source you care about" are different facts, and a paid source
        # sitting off the schedule by design looks like a broken one otherwise.
        "scheduled": [a["name"] for a in avail
                      if a["cadence"] == "scheduled" and a["available"]],
        "on_demand": [a["name"] for a in avail if a["cadence"] == "on_demand"],
        "spend": await spend.month_to_date(),
        "retired": RETIRED,
        "last_scan": await db.fetchrow(
            """
            SELECT started_at, finished_at, ok, detail
            FROM job_runs WHERE job = 'scan'
            ORDER BY started_at DESC LIMIT 1
            """
        ),
    }
