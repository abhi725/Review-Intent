"""Our own MCP server.

A second front end over the same service layer the dashboard uses. Every tool
here is a thin wrapper — if a rule lives in this file, it is in the wrong place.

Run it:
    python -m intentdesk.mcp.server            # stdio, for Claude Code locally
    python -m intentdesk.mcp.server --http     # streamable HTTP on MCP_HTTP_PORT
"""

import sys
from datetime import datetime, timedelta, timezone
from typing import Optional

from mcp.server.fastmcp import FastMCP

from intentdesk import db
from intentdesk.config import settings
from intentdesk.services import (
    companies,
    export,
    leads,
    preferences,
    scan,
    scoring,
    signals,
    watchlist,
)
from intentdesk.services import stats as stats_service

mcp = FastMCP("intent-desk")


async def _ready() -> None:
    """Connect on first use. The stdio transport has no startup hook, so the
    pool is created lazily rather than at import."""
    try:
        db.pool()
    except RuntimeError:
        await db.connect()


def _since(days: Optional[int]) -> Optional[datetime]:
    return datetime.now(timezone.utc) - timedelta(days=days) if days else None


# ------------------------------------------------------------------ leads
@mcp.tool()
async def list_leads(
    heat: Optional[str] = None,
    status: Optional[str] = None,
    city: Optional[str] = None,
    since_days: Optional[int] = None,
    limit: int = 50,
) -> list[dict]:
    """List the lead queue.

    heat: hot | warm | cool. status: NEW | APPROVED | REJECTED | SENT.
    city matches loosely, so "pune" finds Pune.
    """
    await _ready()
    return await leads.list_leads(
        heat=heat, status=status,
        city=f"%{city}%" if city else None,
        since=_since(since_days), limit=limit,
    )


@mcp.tool()
async def get_lead(lead_id: int) -> dict:
    """Full detail for one lead, including every signal behind its score."""
    await _ready()
    lead = await leads.get_lead(lead_id)
    return lead or {"error": f"no lead with id {lead_id}"}


@mcp.tool()
async def set_lead_status(lead_id: int, status: str) -> dict:
    """Approve, reject, or mark a lead sent.

    Rejecting or sending also suppresses the company's domain so it cannot be
    contacted again by a later scan.
    """
    await _ready()
    try:
        result = await leads.set_lead_status(lead_id, status)
    except ValueError as exc:
        return {"error": str(exc)}
    return result or {"error": f"no lead with id {lead_id}"}


@mcp.tool()
async def update_draft(
    lead_id: int, subject: Optional[str] = None, body: Optional[str] = None
) -> dict:
    """Rewrite a lead's draft subject and/or body."""
    await _ready()
    result = await leads.update_draft(lead_id, subject, body)
    return result or {"error": f"no lead with id {lead_id}"}


@mcp.tool()
async def explain_score(lead_id: int) -> dict:
    """Why a lead scored what it did — each signal's contribution after decay.

    Use this before trusting a ranking, or when a lead looks misplaced.
    """
    await _ready()
    lead = await leads.get_lead(lead_id)
    if not lead:
        return {"error": f"no lead with id {lead_id}"}
    band = await preferences.agent_band()
    return {
        "company": lead["company"],
        "score": lead["score"],
        "heat": lead["heat"],
        "breakdown": scoring.explain(lead["signals"], lead["agents_est"], band),
    }


# ---------------------------------------------------------------- signals
@mcp.tool()
async def list_signals(
    kind: Optional[str] = None,
    matched: Optional[bool] = None,
    since_days: Optional[int] = 30,
    limit: int = 50,
) -> list[dict]:
    """Raw intent signals.

    kind: install | job_post | review | forum | vendor_news.
    matched=False returns signals with no company attached — most G2 reviews
    land here, because G2 publishes no company name or domain.
    """
    await _ready()
    return await signals.list_signals(kind, matched, _since(since_days), limit)


@mcp.tool()
async def collector_health(days: int = 7) -> list[dict]:
    """Per-source signal counts. A source at zero usually means a broken
    scraper, not a quiet week — check this before believing an empty queue."""
    await _ready()
    return await signals.collector_health(days)


# ------------------------------------------------------------------- scan
@mcp.tool()
async def run_scan(competitor: Optional[str] = None) -> dict:
    """Collect, match, score and rebuild the queue. Costs money — paid
    collectors bill per run, and the monthly cap is enforced before starting."""
    await _ready()
    return await scan.run(competitor)


@mcp.tool()
async def scan_status() -> dict:
    """Which collectors are wired up and which are waiting on credentials."""
    await _ready()
    return await scan.status()


# -------------------------------------------------------------- watchlist
@mcp.tool()
async def watchlist_list() -> list[dict]:
    """Competitors tracked, with install base, negatives and leads produced."""
    await _ready()
    return await watchlist.list_all()


@mcp.tool()
async def watchlist_add(competitor: str, sources: Optional[list[str]] = None) -> dict:
    """Track a competitor."""
    await _ready()
    return await watchlist.add(competitor, sources)


@mcp.tool()
async def watchlist_remove(competitor: str) -> dict:
    """Stop tracking a competitor. Deactivates rather than deletes, so the
    companies and signals it already produced stay intact."""
    await _ready()
    ok = await watchlist.remove(competitor)
    return {"competitor": competitor, "active": False} if ok else {"error": "not on the watchlist"}


# ------------------------------------------------------ settings & output
@mcp.tool()
async def suppress_domain(domain: str, reason: str = "manual") -> dict:
    """Never contact this domain again."""
    await _ready()
    await companies.suppress(domain, reason)
    return {"domain": domain.lower().strip(), "suppressed": True, "reason": reason}


@mcp.tool()
async def get_settings() -> dict:
    """Current targeting and guardrail settings."""
    await _ready()
    return await preferences.all_prefs()


@mcp.tool()
async def update_settings(changes: dict) -> dict:
    """Change targeting or guardrails, e.g. {"target_agents_max": 150}."""
    await _ready()
    try:
        return await preferences.update(changes)
    except ValueError as exc:
        return {"error": str(exc)}


@mcp.tool()
async def stats() -> dict:
    """Funnel counts: install base, leads by state, identifiable share, spend."""
    await _ready()
    return await stats_service.overview()


@mcp.tool()
async def export_csv(status: Optional[str] = None, heat: Optional[str] = None) -> str:
    """The queue as CSV text."""
    await _ready()
    return await export.leads_csv(status=status, heat=heat)


def main() -> None:
    if "--http" in sys.argv:
        import uvicorn

        uvicorn.run(
            mcp.streamable_http_app(),
            host="0.0.0.0",
            port=settings.mcp_http_port,
        )
    else:
        mcp.run()


if __name__ == "__main__":
    main()
