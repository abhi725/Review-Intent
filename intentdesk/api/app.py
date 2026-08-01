from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.middleware.sessions import SessionMiddleware

from intentdesk import db
from intentdesk.config import ROOT, settings
from intentdesk.services import companies, leads, signals, stats, watchlist


@asynccontextmanager
async def lifespan(app: FastAPI):
    await db.connect()
    yield
    await db.disconnect()


app = FastAPI(title="Intent Desk", version="0.1.0", lifespan=lifespan)
app.add_middleware(SessionMiddleware, secret_key=settings.session_secret)


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
    if not email.endswith("@" + settings.allowed_email_domain):
        raise HTTPException(status_code=403, detail="Outside the allowed email domain")
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


# ----------------------------------------------- static dashboard bundle
_DIST = ROOT / "web" / "dist"
if _DIST.is_dir():
    app.mount("/", StaticFiles(directory=str(_DIST), html=True), name="dashboard")
