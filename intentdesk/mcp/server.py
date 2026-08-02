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
    monitoring,
    preferences,
    scan,
    scoring,
    signals,
    watchlist,
)
from intentdesk.services import stats as stats_service

# streamable_http_path="/" puts the endpoint at the mount root. The default is
# "/mcp", which would land at /mcp/mcp once mounted under /mcp in the API app.
mcp = FastMCP("intent-desk", streamable_http_path="/")


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
async def enrich_companies(limit: int = 25) -> dict:
    """Enrich companies via Apollo: firmographics, phone, and the ticketing
    platform they actually run. Apollo's free plan has no person endpoints, so
    this returns company-level data only — a phone number, never an email."""
    await _ready()
    from intentdesk.services import enrichment

    return await enrichment.enrich_pending(limit)


@mcp.tool()
async def redraft(lead_id: int) -> dict:
    """Regenerate a lead's outreach draft with the configured LLM provider.

    The draft never references the review, post, or job listing that surfaced
    the lead — it speaks to the industry problem instead.
    """
    await _ready()
    from intentdesk import llm as llm_mod
    from intentdesk.services import drafting

    try:
        return await drafting.draft_for_lead(lead_id)
    except (ValueError, llm_mod.LLMError) as exc:
        return {"error": str(exc)}


@mcp.tool()
async def llm_status() -> dict:
    """Which LLM providers are configured and which one is active."""
    from intentdesk import llm as llm_mod

    return llm_mod.status()


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
async def run_scan(competitor: Optional[str] = None, free_only: bool = False) -> dict:
    """Collect, match, score and rebuild the queue.

    Costs money — paid collectors bill per run, and the monthly cap is enforced
    before starting. Pass free_only=True to run only the collectors that cost
    nothing, which exercises the whole pipeline without committing budget.
    """
    await _ready()
    return await scan.run(competitor, free_only=free_only)


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


@mcp.tool()
async def suppress_domains(domains: list[str], reason: str = "bulk upload") -> dict:
    """Never contact these domains again — a whole do-not-contact list at once.

    Use for existing customers, live deals, and anyone who has asked not to be
    contacted. Tolerates URLs and email addresses; reports what it could not
    parse rather than dropping it.
    """
    await _ready()
    return await companies.suppress_bulk(domains, reason)


@mcp.tool()
async def unsuppress_domain(domain: str) -> dict:
    """Remove a domain from the suppression list so it can surface again."""
    await _ready()
    result = await db.execute(
        "DELETE FROM suppression WHERE domain = $1", domain.lower().strip()
    )
    if result.endswith("0"):
        return {"error": f"{domain} was not suppressed"}
    return {"domain": domain.lower().strip(), "suppressed": False}


@mcp.tool()
async def enrich_company(company_id: int) -> dict:
    """Enrich one specific company via Apollo, rather than a whole batch."""
    await _ready()
    from intentdesk.services import enrichment

    try:
        return await enrichment.enrich_company(company_id)
    except (ValueError, enrichment.EnrichmentUnavailable) as exc:
        return {"error": str(exc)}


@mcp.tool()
async def draft_pending(limit: int = 10) -> dict:
    """Draft outreach for the top contactable leads that have none yet.

    On the phone channel this writes a spoken call opener, not an email — the
    artifact follows the configured outreach channel.
    """
    await _ready()
    from intentdesk.services import drafting

    return await drafting.draft_pending(limit)


# ----------------------------------------------------------- monitoring
@mcp.tool()
async def alerts() -> list[dict]:
    """Everything currently wrong, worst first; empty means healthy.

    Catches the two failures the queue cannot show: a collector that stopped
    returning anything, and a cron that stopped firing. Check this before
    concluding a quiet week is genuinely quiet.
    """
    await _ready()
    return await monitoring.alerts()


@mcp.tool()
async def digest(days: int = 7, as_text: bool = False) -> dict | str:
    """New leads, counts, spend and open alerts for the period."""
    await _ready()
    data = await monitoring.digest(days)
    return monitoring.render_digest(data) if as_text else data


@mcp.tool()
async def reconcile_spend() -> dict:
    """Check recorded spend against Apify's own monthly figure.

    A gap means runs billed that this system never recorded — the direction that
    lets the cap be enforced against an understatement.
    """
    await _ready()
    return await monitoring.reconcile_spend()


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
