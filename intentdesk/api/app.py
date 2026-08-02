from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.middleware.sessions import SessionMiddleware

from intentdesk import db
from intentdesk.config import ROOT, settings
from intentdesk.services import (
    companies,
    export,
    leads,
    monitoring,
    preferences,
    scan,
    signals,
    stats,
    watchlist,
)


from intentdesk.api.bearer import BearerAuthASGI, NormalizeMountPath
from intentdesk.mcp.server import mcp as mcp_server

# Build the ASGI app first — FastMCP creates the session manager lazily and it
# is only reachable after this call.
_mcp_asgi = mcp_server.streamable_http_app()


@asynccontextmanager
async def lifespan(app: FastAPI):
    await db.connect()
    # A mounted sub-app's own lifespan never runs, so the MCP session manager
    # has to be started here. Without it every /mcp request hangs.
    async with mcp_server.session_manager.run():
        yield
    await db.disconnect()


app = FastAPI(title="Intent Desk", version="0.1.0", lifespan=lifespan)
app.add_middleware(SessionMiddleware, secret_key=settings.session_secret)
app.add_middleware(NormalizeMountPath, mount="/mcp")


# ----------------------------------------------------------------- auth
def require_user(request: Request) -> dict:
    """Session gate.

    In dev there is no login — the app is bound to loopback. In any other
    environment a Google session is mandatory.
    """
    if settings.is_dev:
        return {"email": "dev@localhost", "name": "Dev"}
    user = request.session.get("user")
    if not user:
        raise HTTPException(status_code=401, detail="Not signed in")
    return user


def _oauth():
    from authlib.integrations.starlette_client import OAuth

    oauth = OAuth()
    oauth.register(
        name="google",
        client_id=settings.google_client_id,
        client_secret=settings.google_client_secret,
        server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
        client_kwargs={"scope": "openid email profile"},
    )
    return oauth


@app.get("/auth/login")
async def login(request: Request):
    redirect_uri = request.url_for("auth_callback")
    return await _oauth().google.authorize_redirect(request, str(redirect_uri))


@app.get("/auth/callback", name="auth_callback")
async def auth_callback(request: Request):
    token = await _oauth().google.authorize_access_token(request)
    info = token.get("userinfo") or {}
    email = (info.get("email") or "").lower()
    allowed = settings.allowed_email_domains
    if not any(email.endswith("@" + d) for d in allowed):
        # Name the domains, otherwise a rejected sign-in is undiagnosable from
        # the browser — Google succeeded and only this check refused.
        raise HTTPException(
            status_code=403,
            detail=f"{email} is not permitted. Allowed: {', '.join(allowed)}",
        )
    request.session["user"] = {"email": email, "name": info.get("name", email)}
    return RedirectResponse("/")


@app.get("/auth/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/")


@app.get("/api/me")
async def me(user: dict = Depends(require_user)):
    return user


# --------------------------------------------------------------- health
@app.get("/health")
async def health():
    try:
        await db.fetchval("SELECT 1")
    except Exception as exc:  # surfaced so a failing deploy is obvious
        raise HTTPException(status_code=503, detail=f"database unreachable: {exc}")
    return {"status": "ok", "env": settings.app_env}


# ---------------------------------------------------------------- leads
class LeadPatch(BaseModel):
    status: Optional[str] = None
    draft_subject: Optional[str] = None
    draft_body: Optional[str] = None


@app.get("/api/leads")
async def api_list_leads(
    heat: Optional[str] = None,
    status: Optional[str] = None,
    city: Optional[str] = None,
    since: Optional[datetime] = None,
    limit: int = Query(100, le=500),
    offset: int = 0,
    user: dict = Depends(require_user),
):
    return await leads.list_leads(heat, status, city, since, limit, offset)


@app.get("/api/leads/{lead_id}")
async def api_get_lead(lead_id: int, user: dict = Depends(require_user)):
    lead = await leads.get_lead(lead_id)
    if lead is None:
        raise HTTPException(status_code=404, detail="No such lead")
    return lead


@app.patch("/api/leads/{lead_id}")
async def api_patch_lead(
    lead_id: int, patch: LeadPatch, user: dict = Depends(require_user)
):
    result = None
    if patch.draft_subject is not None or patch.draft_body is not None:
        result = await leads.update_draft(lead_id, patch.draft_subject, patch.draft_body)
    if patch.status is not None:
        try:
            result = await leads.set_lead_status(lead_id, patch.status)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
    if result is None:
        raise HTTPException(status_code=404, detail="No such lead")
    return result


# -------------------------------------------------------------- signals
@app.get("/api/signals")
async def api_signals(
    kind: Optional[str] = None,
    matched: Optional[bool] = None,
    since: Optional[datetime] = None,
    limit: int = Query(100, le=500),
    user: dict = Depends(require_user),
):
    return await signals.list_signals(kind, matched, since, limit)


@app.get("/api/signals/health")
async def api_signal_health(days: int = 7, user: dict = Depends(require_user)):
    return await signals.collector_health(days)


# ------------------------------------------------------------ watchlist
class WatchlistAdd(BaseModel):
    competitor: str
    sources: Optional[list[str]] = None


@app.get("/api/watchlist")
async def api_watchlist(active_only: bool = False, user: dict = Depends(require_user)):
    return await watchlist.list_all(active_only)


@app.post("/api/watchlist")
async def api_watchlist_add(body: WatchlistAdd, user: dict = Depends(require_user)):
    return await watchlist.add(body.competitor, body.sources)


@app.delete("/api/watchlist/{competitor}")
async def api_watchlist_remove(competitor: str, user: dict = Depends(require_user)):
    if not await watchlist.remove(competitor):
        raise HTTPException(status_code=404, detail="Not on the watchlist")
    return {"competitor": competitor, "active": False}


# ------------------------------------------------------------- drafting
@app.get("/api/llm/status")
async def api_llm_status(user: dict = Depends(require_user)):
    """Which LLM providers are configured, in fallback order."""
    from intentdesk import llm

    return llm.status()


@app.post("/api/leads/{lead_id}/draft")
async def api_draft_lead(lead_id: int, user: dict = Depends(require_user)):
    from intentdesk import llm
    from intentdesk.services import drafting

    try:
        return await drafting.draft_for_lead(lead_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except llm.LLMError as exc:
        raise HTTPException(status_code=503, detail=str(exc))


@app.post("/api/drafts/generate")
async def api_draft_pending(limit: int = 10, user: dict = Depends(require_user)):
    """Draft for the top contactable leads that don't have one yet."""
    from intentdesk.services import drafting

    return await drafting.draft_pending(limit)


# ----------------------------------------------------------- enrichment
@app.post("/api/companies/{company_id}/enrich")
async def api_enrich_company(company_id: int, user: dict = Depends(require_user)):
    from intentdesk.services import enrichment

    try:
        return await enrichment.enrich_company(company_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except enrichment.EnrichmentUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc))


@app.post("/api/enrich")
async def api_enrich_pending(limit: int = 25, user: dict = Depends(require_user)):
    """Enrich the least-recently-enriched companies via Apollo."""
    from intentdesk.services import enrichment

    return await enrichment.enrich_pending(limit)


# ----------------------------------------------------------------- scan
@app.post("/api/scan")
async def api_scan(
    competitor: Optional[str] = None,
    free_only: bool = False,
    user: dict = Depends(require_user),
):
    """Collect, match, score, rebuild the queue. Also the n8n cron target."""
    return await scan.run(competitor, free_only=free_only)


@app.get("/api/scan/status")
async def api_scan_status(user: dict = Depends(require_user)):
    """Which collectors are wired up and which are waiting on a token."""
    return await scan.status()


# --------------------------------------------------------- monitoring
@app.get("/api/alerts")
async def api_alerts(user: dict = Depends(require_user)):
    """Everything currently wrong, worst first. Empty means healthy."""
    return await monitoring.alerts()


@app.get("/api/digest")
async def api_digest(
    days: int = 7, fmt: str = "json", user: dict = Depends(require_user)
):
    data = await monitoring.digest(days)
    if fmt == "text":
        return Response(content=monitoring.render_digest(data), media_type="text/plain")
    return data


@app.post("/api/spend/reconcile")
async def api_reconcile(user: dict = Depends(require_user)):
    """Compare recorded spend against Apify's own monthly figure."""
    return await monitoring.reconcile_spend()


# ----------------------------------------------------------------- cron
# n8n has no Google session and cannot get one, so the scheduled entry points
# authenticate with the same bearer token as MCP. Mounted as a sub-app for the
# same reason the MCP app is: the token check has to run before routing, not as
# a per-route dependency that a future endpoint could forget to declare.
cron = FastAPI(title="Intent Desk cron", docs_url=None, redoc_url=None)


@cron.post("/scan")
async def cron_scan(competitor: Optional[str] = None, free_only: bool = False):
    return await scan.run(competitor, free_only=free_only)


@cron.post("/enrich")
async def cron_enrich(limit: int = 25):
    from intentdesk.services import enrichment

    return await enrichment.enrich_pending(limit)


@cron.post("/draft")
async def cron_draft(limit: int = 10):
    from intentdesk.services import drafting

    return await drafting.draft_pending(limit)


@cron.get("/digest")
async def cron_digest(days: int = 7, fmt: str = "text"):
    data = await monitoring.digest(days)
    if fmt == "text":
        return Response(content=monitoring.render_digest(data), media_type="text/plain")
    return data


@cron.get("/alerts")
async def cron_alerts():
    return await monitoring.alerts()


@cron.post("/reconcile")
async def cron_reconcile():
    return await monitoring.reconcile_spend()


app.mount("/cron", BearerAuthASGI(cron, settings.mcp_bearer_token, realm="intent-desk-cron"))


# ------------------------------------------------------------- settings
@app.get("/api/stats")
async def api_stats(user: dict = Depends(require_user)):
    return await stats.overview()


@app.get("/api/suppression")
async def api_suppression(user: dict = Depends(require_user)):
    return await db.fetch(
        "SELECT domain, reason, added_at FROM suppression ORDER BY added_at DESC LIMIT 500"
    )


class SuppressBody(BaseModel):
    domain: str
    reason: str = "manual"


@app.post("/api/suppression")
async def api_suppress(body: SuppressBody, user: dict = Depends(require_user)):
    await companies.suppress(body.domain, body.reason)
    return {"domain": body.domain.lower().strip(), "reason": body.reason}


class SuppressBulkBody(BaseModel):
    domains: Optional[list[str]] = None
    text: Optional[str] = None
    reason: str = "bulk upload"


@app.post("/api/suppression/bulk")
async def api_suppress_bulk(
    body: SuppressBulkBody, user: dict = Depends(require_user)
):
    """Load a do-not-contact list. Accepts a JSON array or pasted text —
    newline, comma or semicolon separated, and tolerant of URLs and emails."""
    items = list(body.domains or [])
    if body.text:
        items += [part for chunk in body.text.splitlines()
                  for part in chunk.replace(";", ",").split(",")]
    if not items:
        raise HTTPException(status_code=422, detail="No domains supplied")
    return await companies.suppress_bulk(items, body.reason)


@app.delete("/api/suppression/{domain}")
async def api_unsuppress(domain: str, user: dict = Depends(require_user)):
    result = await db.execute(
        "DELETE FROM suppression WHERE domain = $1", domain.lower().strip()
    )
    if result.endswith("0"):
        raise HTTPException(status_code=404, detail="Not on the suppression list")
    return {"domain": domain.lower().strip(), "suppressed": False}


# ------------------------------------------------------- runtime settings
@app.get("/api/settings")
async def api_get_settings(user: dict = Depends(require_user)):
    return await preferences.all_prefs()


@app.patch("/api/settings")
async def api_patch_settings(body: dict, user: dict = Depends(require_user)):
    try:
        return await preferences.update(body)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


# ---------------------------------------------------------------- export
@app.get("/api/export/leads.csv")
async def api_export_csv(
    status: Optional[str] = None,
    heat: Optional[str] = None,
    user: dict = Depends(require_user),
):
    """Download the queue. Sheets imports this directly via File → Import."""
    body = await export.leads_csv(status=status, heat=heat)
    return Response(
        content=body,
        media_type="text/csv",
        headers={"content-disposition": 'attachment; filename="intent-desk-leads.csv"'},
    )


# ------------------------------------------------------ MCP over HTTP
# Mounted here rather than on its own subdomain: no DNS record, no second
# container, and TLS is already terminated for this host. Must be mounted
# before the catch-all static mount below, since routes match in order.
app.mount("/mcp", BearerAuthASGI(_mcp_asgi, settings.mcp_bearer_token))


# ----------------------------------------------- static dashboard bundle
_DIST = ROOT / "web" / "dist"
if _DIST.is_dir():
    app.mount("/", StaticFiles(directory=str(_DIST), html=True), name="dashboard")
