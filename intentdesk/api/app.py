from contextlib import asynccontextmanager
from datetime import datetime
from typing import Optional
from urllib.parse import quote

from fastapi import Depends, FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    PlainTextResponse,
    RedirectResponse,
    Response,
)
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.middleware.sessions import SessionMiddleware

from intentdesk import db
from intentdesk.api import landing as landing_module
from intentdesk.api import pages
from intentdesk.config import ROOT, settings
from intentdesk.services import users
from intentdesk.services import (
    avatars,
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


# Where the built dashboard lives. Defined here rather than beside the mount at
# the bottom because the /app route needs it too, and a route that reads a
# global defined 600 lines later works but reads like an accident.
_DIST = ROOT / "web" / "dist"
_DIST_INDEX = _DIST / "index.html"

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
        return {"email": "dev@localhost", "name": "Dev", "is_admin": True}
    user = request.session.get("user")
    if not user:
        raise HTTPException(status_code=401, detail="Not signed in")
    return user


def require_admin(user: dict = Depends(require_user)) -> dict:
    """Account administration. The first account created becomes the admin, so
    a fresh deploy is never locked out of its own access settings."""
    if not user.get("is_admin"):
        raise HTTPException(status_code=403, detail="Admins only")
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


# --------------------------------------------------- public landing + app shell
# Same ordering rule as the auth pages below: the StaticFiles catch-all at "/"
# is registered last, so anything that must not be served from web/dist has to
# be declared before it.
@app.get("/", response_class=HTMLResponse)
async def landing():
    """The public front door. No session required — that is the whole point."""
    return HTMLResponse(landing_module.landing_page())


@app.get("/app", response_class=HTMLResponse)
async def app_shell():
    """The dashboard. Moved off "/" so the landing page can have it.

    The SPA keeps its screen in `useState` rather than the URL, so there are no
    deep links under /app to route — one file is the whole surface.
    """
    index = _DIST_INDEX
    if not index.is_file():
        raise HTTPException(
            status_code=503,
            detail="Dashboard bundle is missing — run `npm run build` in web/.",
        )
    return FileResponse(index)


async def _public_leads_csv(token: str, cacheable: bool):
    """Shared body for the two public CSV paths. See `public_leads_csv`."""
    from intentdesk.services import export

    # 404 rather than 401/403 for both "switched off" and "wrong token". A 403
    # would confirm that a valid URL of this shape exists and that the guess was
    # merely wrong, which is exactly the signal a guesser wants.
    if not export.sheet_export_token_ok(token):
        raise HTTPException(status_code=404, detail="Not found")

    # No BOM: this is read by IMPORTDATA, which would put it inside the first
    # column heading. The browser download keeps its BOM for Excel's sake.
    body = await export.leads_csv(bom=False)
    return PlainTextResponse(
        body,
        media_type="text/csv; charset=utf-8",
        headers={
            # Belt and braces with robots.txt: a Disallow asks a crawler not to
            # fetch, while this tells anything that did fetch not to index.
            "X-Robots-Tag": "noindex, nofollow",
            # On the extensionless path, ask for no caching at all. Cloudflare
            # treats that route as dynamic, so what we send is what applies, and a
            # rotated token or a new lead should be visible immediately.
            "Cache-Control": ("public, max-age=300" if cacheable
                              else "no-store, max-age=0"),
        },
    )


@app.get("/export/leads/{token}", response_class=PlainTextResponse)
async def public_leads_csv_nocache(token: str):
    """The path to actually use. Same data as the `.csv` one, without the cache.

    **Cloudflare caches by file extension**, measured 2026-08-03: the `.csv` URL
    came back with `max-age=14400` — Cloudflare rewriting our `max-age=300` — while
    an extensionless route under the same hostname is `cf-cache-status: DYNAMIC`
    and not cached at all. Four hours of staleness on a lead feed is bad on its own
    and worse for rotation, because a revoked token would keep serving from the
    edge after it stopped being valid at the origin.

    IMPORTDATA does not need the extension; it parses on content, and the response
    is `text/csv`. The `.csv` route is kept only as a fallback in case a particular
    Sheets version disagrees.
    """
    return await _public_leads_csv(token, cacheable=False)


@app.get("/export/leads-{token}.csv", response_class=PlainTextResponse)
async def public_leads_csv(token: str):
    """The lead queue as CSV, for Google Sheets' IMPORTDATA. **Unauthenticated.**

    This is the one deliberately public data path in the application, and it earns
    that by being the only thing that works: IMPORTDATA cannot send an
    Authorization header, so a bearer-token route is unreachable from a
    spreadsheet formula. The secret therefore lives in the URL, and **anyone
    holding the URL can read the lead queue** — company names, domains, phones and
    the drafted outreach. That was accepted explicitly as the trade-off for a
    one-formula setup after the OAuth, service-account and Apps Script routes all
    failed.

    What it does *not* do is pretend otherwise. It is off unless a token of at
    least 24 characters is configured, a wrong token is indistinguishable from a
    route that does not exist, and the comparison is constant-time so the token
    cannot be guessed a character at a time. Rotate by changing
    SHEET_EXPORT_TOKEN and re-pasting the formula; the old URL dies immediately.

    Registered before the StaticFiles catch-all at "/", or the mount would swallow
    it.

    Prefer `/export/leads/{token}`: Cloudflare caches this one for four hours
    because of the `.csv` extension, regardless of what we ask for.
    """
    return await _public_leads_csv(token, cacheable=True)


@app.get("/robots.txt", response_class=PlainTextResponse)
async def robots():
    # The landing page is the only thing worth indexing. Everything else is
    # either behind a session or an API.
    # Everything not listed is allowed by default, so "/" needs no Allow rule.
    # No Sitemap directive: that must point at an XML sitemap, and there is not
    # one — naming the homepage there is simply an invalid line.
    return PlainTextResponse(
        "User-agent: *\n"
        "Disallow: /app\n"
        "Disallow: /api/\n"
        "Disallow: /mcp\n"
        "Disallow: /cron\n"
        # The public CSV export. Unguessable, but a crawler that finds the URL
        # anywhere — a pasted link, a referrer header — must not index the lead
        # queue into a search result.
        "Disallow: /export/\n"
        "Disallow: /login\n"
        "Disallow: /signup\n"
        "Disallow: /reset\n"
        "Disallow: /verify\n"
        "Disallow: /forgot\n"
    )


# ------------------------------------------------------ sign-in / sign-up pages
# Registered before the static mount, because routes match in order and the
# catch-all at "/" would otherwise swallow both.
@app.get("/login", response_class=HTMLResponse)
async def login_page(
    error: str = "", notice: str = "", email: str = "", unverified: str = ""
):
    return HTMLResponse(
        pages.login_page(
            await users.access_mode(), await users.allowed_domains(),
            error=error, notice=notice, email=email, unverified=bool(unverified),
        )
    )


@app.get("/signup", response_class=HTMLResponse)
async def signup_page(error: str = "", notice: str = "", email: str = "", name: str = ""):
    return HTMLResponse(
        pages.signup_page(
            await users.access_mode(), await users.allowed_domains(),
            error=error, notice=notice, email=email, name=name,
        )
    )


@app.get("/auth/callback", name="auth_callback")
async def auth_callback(request: Request):
    try:
        token = await _oauth().google.authorize_access_token(request)
    except Exception:
        # An expired or replayed state lands here. Sending the person back to a
        # branded page with a readable reason beats a raw traceback.
        return RedirectResponse(
            "/login?error=" + quote("Sign-in with Google did not complete. Try again."),
            status_code=303,
        )

    info = token.get("userinfo") or {}
    email = (info.get("email") or "").lower()

    # Google says whether it verified the address. Accepting an unverified one
    # would let someone claim an address they do not control — which, with any
    # domain rule in force, is exactly the check being bypassed.
    if not info.get("email_verified", True):
        return RedirectResponse(
            "/login?error=" + quote("Google has not verified that address."),
            status_code=303,
        )

    try:
        user = await users.upsert_google(
            sub=info.get("sub") or email,
            email=email,
            name=info.get("name") or "",
        )
    except users.AuthError as exc:
        return RedirectResponse("/login?error=" + quote(str(exc)), status_code=303)

    request.session["user"] = user
    # /app, not / — "/" is the marketing page now, and landing back on it after
    # signing in reads as the sign-in having failed.
    return RedirectResponse("/app", status_code=303)


@app.post("/auth/password")
async def auth_password(request: Request):
    form = await request.form()
    email = str(form.get("email") or "")
    try:
        user = await users.authenticate(email, str(form.get("password") or ""))
    except users.UnverifiedError as exc:
        # Distinct from a bad password so the page can offer a resend link.
        # Only reachable once the password was right, so it reveals nothing.
        return RedirectResponse(
            f"/login?error={quote(str(exc))}&email={quote(email)}&unverified=1",
            status_code=303,
        )
    except users.AuthError as exc:
        return RedirectResponse(
            f"/login?error={quote(str(exc))}&email={quote(email)}", status_code=303
        )
    request.session["user"] = user
    # /app, not / — "/" is the marketing page now, and landing back on it after
    # signing in reads as the sign-in having failed.
    return RedirectResponse("/app", status_code=303)


@app.post("/auth/register")
async def auth_register(request: Request):
    form = await request.form()
    email = str(form.get("email") or "")
    name = str(form.get("name") or "")
    try:
        result = await users.register(email, str(form.get("password") or ""), name)
    except users.AuthError as exc:
        return RedirectResponse(
            f"/signup?error={quote(str(exc))}&email={quote(email)}&name={quote(name)}",
            status_code=303,
        )

    if result.get("created"):
        # No-op for the first account, which is created pre-verified.
        await users.send_verification(email)
    else:
        # The address already has an account. The form below cannot say so
        # without becoming an address-enumeration oracle, so the explanation
        # goes to the address itself. Skipping this is what made a duplicate
        # signup a dead end: "check your email", and nothing ever sent.
        await users.send_existing_account_notice(email)

    # Same message either way. Telling a fresh signup apart from a duplicate
    # turns this form into a way to test which addresses exist.
    notice = "Check your email for a confirmation link, then sign in."
    if result.get("created") and not email_configured():
        # A deploy with no mail channel would otherwise leave someone waiting
        # for a link that was never sent.
        notice = "Account created. Ask an admin for a confirmation link — this deploy cannot send email."
    return RedirectResponse("/login?notice=" + quote(notice), status_code=303)


def email_configured() -> bool:
    from intentdesk.services import email as mailer

    return mailer.configured()


# ------------------------------------------------------- verify / reset pages
@app.get("/verify", response_class=HTMLResponse)
async def verify_page(token: str = ""):
    try:
        claim = await users.consume_token(token, "verify")
    except users.AuthError as exc:
        return HTMLResponse(pages.outcome_page("Link expired", str(exc)), status_code=400)
    await users.mark_verified(claim["user_id"])
    return RedirectResponse(
        "/login?notice=" + quote("Email confirmed. Sign in below."), status_code=303
    )


@app.post("/auth/verify/resend")
async def auth_verify_resend(request: Request):
    form = await request.form()
    await users.send_verification(str(form.get("email") or ""))
    # Unconditional message — see send_verification, which is silent for an
    # unknown or already-verified address.
    return RedirectResponse(
        "/login?notice=" + quote("If that address needs confirming, a new link is on its way."),
        status_code=303,
    )


@app.get("/forgot", response_class=HTMLResponse)
async def forgot_page(error: str = "", notice: str = "", email: str = ""):
    return HTMLResponse(pages.forgot_page(error=error, notice=notice, email=email))


@app.post("/auth/forgot")
async def auth_forgot(request: Request):
    form = await request.form()
    await users.send_reset(str(form.get("email") or ""))
    return RedirectResponse(
        "/forgot?notice=" + quote("If that address has an account, a link is on its way."),
        status_code=303,
    )


@app.get("/reset", response_class=HTMLResponse)
async def reset_page(token: str = "", error: str = ""):
    # The token is only checked for shape here; it is redeemed on submit, so a
    # link preview fetched by a mail client cannot burn it.
    if not token:
        return HTMLResponse(
            pages.outcome_page("Link expired", "This link is no longer valid. Request a new one."),
            status_code=400,
        )
    return HTMLResponse(pages.reset_page(token=token, error=error))


@app.post("/auth/reset")
async def auth_reset(request: Request):
    form = await request.form()
    token = str(form.get("token") or "")
    password = str(form.get("password") or "")

    problem = users.password_problem(password)
    if problem:
        return RedirectResponse(
            f"/reset?token={quote(token)}&error={quote(problem)}", status_code=303
        )
    try:
        claim = await users.consume_token(token, "reset")
        await users.set_password(claim["user_id"], password)
    except users.AuthError as exc:
        return HTMLResponse(pages.outcome_page("Link expired", str(exc)), status_code=400)

    # Clicking a link in that inbox proves the same thing verification proves.
    await users.mark_verified(claim["user_id"])
    return RedirectResponse(
        "/login?notice=" + quote("Password updated. Sign in below.")
        + f"&email={quote(claim['email'])}",
        status_code=303,
    )


@app.get("/auth/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)


STALE_SESSION = (
    "Your sign-in predates accounts on this deploy, so there is no profile "
    "behind it yet. Sign out and sign in again — it takes one click and "
    "creates the account."
)


async def _own_profile(user: dict) -> dict:
    """The signed-in user's database row, or a readable refusal.

    A valid session with no row behind it is a real state, not a bug: before
    `004_users`, signing in with Google minted a cookie and persisted nothing.
    Those cookies are still signed with the same SESSION_SECRET and still
    authenticate, so anyone holding one reaches the profile endpoints with
    nothing to update. A bare 404 makes that look broken; this says what to do.
    """
    profile = await users.get_profile(user["email"])
    if profile is None:
        raise HTTPException(status_code=409, detail=STALE_SESSION)
    return profile


@app.get("/api/me")
async def me(user: dict = Depends(require_user)):
    profile = await users.get_profile(user["email"])
    if profile is None:
        # Dev mode has a synthetic session with no row behind it, and so does a
        # pre-004 Google cookie. Report it rather than 409-ing the whole
        # dashboard: the app is perfectly usable, only the profile is not.
        return {
            **user,
            "has_avatar": False,
            "email_verified": True,
            "stale_session": True,
        }
    return {
        "email": profile["email"],
        "name": profile["name"],
        "is_admin": profile["is_admin"],
        "job_title": profile["job_title"],
        "phone": profile["phone"],
        "has_avatar": profile["has_avatar"],
        "has_password": profile["has_password"],
        "has_google": profile["has_google"],
        "email_verified": profile["email_verified_at"] is not None,
        "avatar_updated_at": profile["avatar_updated_at"],
    }


class ProfilePatch(BaseModel):
    name: Optional[str] = None
    job_title: Optional[str] = None
    phone: Optional[str] = None


@app.patch("/api/me")
async def api_patch_me(patch: ProfilePatch, user: dict = Depends(require_user)):
    await _own_profile(user)
    updated = await users.update_profile(
        user["email"], name=patch.name, job_title=patch.job_title, phone=patch.phone
    )
    return {"email": updated["email"], "name": updated["name"],
            "job_title": updated["job_title"], "phone": updated["phone"]}


class PasswordChange(BaseModel):
    current: str = ""
    new_password: str


@app.post("/api/me/password")
async def api_change_password(body: PasswordChange, user: dict = Depends(require_user)):
    try:
        await users.change_own_password(user["email"], body.current, body.new_password)
    except users.AuthError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return {"ok": True}


@app.post("/api/me/avatar")
async def api_upload_avatar(file: UploadFile = File(...), user: dict = Depends(require_user)):
    # Without this the UPDATE matches zero rows and reports success, so the
    # photo appears to upload and silently vanishes on reload.
    await _own_profile(user)
    # Read with a ceiling rather than trusting content-length, which is
    # client-supplied. One byte over the limit is enough to reject on.
    raw = await file.read(avatars.MAX_UPLOAD_BYTES + 1)
    try:
        png = avatars.normalise(raw)
    except avatars.AvatarError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    await users.set_avatar(user["email"], png)
    return {"ok": True, "bytes": len(png)}


@app.delete("/api/me/avatar")
async def api_delete_avatar(user: dict = Depends(require_user)):
    await users.clear_avatar(user["email"])
    return {"ok": True}


@app.get("/api/users/{email}/avatar")
async def api_get_avatar(email: str, request: Request, user: dict = Depends(require_user)):
    row = await users.get_avatar(email)
    if not row:
        raise HTTPException(status_code=404, detail="No avatar")

    # Weak validator off the update timestamp: the browser re-requests the image
    # on every screen change otherwise, and these are served from Postgres.
    etag = f'W/"{int(row["avatar_updated_at"].timestamp())}"'
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304)
    return Response(
        content=row["avatar"],
        media_type=row["avatar_mime"] or "image/png",
        headers={"etag": etag, "cache-control": "private, max-age=300"},
    )


@app.get("/api/users")
async def api_users(user: dict = Depends(require_admin)):
    """Who has an account, how they sign in, and when they last did."""
    return await users.list_users()


class UserPatch(BaseModel):
    disabled: Optional[bool] = None
    verified: Optional[bool] = None


@app.patch("/api/users/{email}")
async def api_patch_user(
    email: str, patch: UserPatch, admin: dict = Depends(require_admin)
):
    result = None
    if patch.disabled is not None:
        if email.strip().lower() == admin["email"].strip().lower():
            # Otherwise the last admin can disable themselves and the only way
            # back in is a psql session against the container.
            raise HTTPException(
                status_code=422, detail="You cannot disable your own account"
            )
        result = await users.set_disabled(email, patch.disabled)
        if result is None:
            raise HTTPException(status_code=404, detail="No such account")

    if patch.verified:
        # The manual way through, for when mail is broken or the address is a
        # distribution list nobody clicks links in.
        profile = await users.get_profile(email)
        if profile is None:
            raise HTTPException(status_code=404, detail="No such account")
        await users.mark_verified(profile["id"])
        result = {"email": profile["email"], "verified": True}

    if result is None:
        raise HTTPException(status_code=422, detail="Nothing to change")
    return result


@app.post("/api/users/{email}/reset-link")
async def api_admin_reset_link(email: str, admin: dict = Depends(require_admin)):
    """A reset URL to deliver by hand. The path that still works when mail does
    not — worth keeping precisely because SMTP and API credentials rot quietly.
    """
    try:
        return await users.admin_reset_link(email, issued_by=admin["email"])
    except users.AuthError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


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
    platform: Optional[str] = None,
    source_site: Optional[str] = None,
    rating_lte: Optional[float] = Query(None, ge=1, le=5),
    country: Optional[str] = None,
    category: Optional[str] = None,
    until: Optional[datetime] = None,
    switched_only: bool = False,
    user: dict = Depends(require_user),
):
    """The feed. `platform` is the competitor, `source_site` the review site —
    the two levels of the selector, with the rest as filters beneath them."""
    return await signals.list_signals(
        kind, matched, since, limit,
        platform=platform,
        source_site=source_site,
        rating_lte=rating_lte,
        country=country,
        category=category,
        until=until,
        switched_only=switched_only,
    )


@app.get("/api/signals/facets")
async def api_signal_facets(user: dict = Depends(require_user)):
    """What the selector should offer, derived from stored rows rather than
    from the watchlist — so it can never present a competitor with nothing
    behind it, which reads as a broken filter rather than an honest absence."""
    return await signals.feed_facets()


@app.get("/api/organisers")
async def api_organisers(
    status: str = Query("needs_review"),
    limit: int = Query(100, le=500),
    user: dict = Depends(require_user),
):
    """The discovery queue. Defaults to `needs_review`, because that is the only
    state that needs a person: a domain was found but the match was not
    confident enough to act on."""
    return await db.fetch(
        """
        SELECT id, name, platform, source, profile_url, city,
               resolved_domain, resolved_phone, resolved_address,
               resolved_category, resolve_source, resolve_confidence,
               status, company_id, discovered_at, resolved_at
        FROM organisers
        WHERE ($1 = 'all' OR status = $1)
        ORDER BY updated_at DESC
        LIMIT $2
        """,
        status,
        limit,
    )


@app.get("/api/organisers/stats")
async def api_organiser_stats(user: dict = Depends(require_user)):
    from intentdesk.services import resolving

    return await resolving.queue_stats()


@app.post("/api/discover")
async def api_discover(
    limit: int = Query(500, le=2000),
    user: dict = Depends(require_admin),
):
    """Walk the organiser sitemaps. Free — no actor, no credits, no key."""
    from intentdesk.collectors import organisers

    return await organisers.discover(limit=limit)


@app.post("/api/resolve")
async def api_resolve(
    limit: int = Query(25, le=200),
    use_gmb: bool = True,
    user: dict = Depends(require_admin),
):
    """Resolve pending organisers into companies. **Costs money** (~$0.0027 per
    GMB lookup), so it is admin-only, batched and resumable rather than a cron
    job. The response carries the actual spend and what is left."""
    from intentdesk.services import resolving

    return await resolving.resolve_batch(limit=limit, use_gmb=use_gmb)


@app.post("/api/organisers/{organiser_id}/promote")
async def api_promote_organiser(
    organiser_id: int,
    user: dict = Depends(require_admin),
):
    """Accept a `needs_review` match by hand.

    The confidence gate holds fuzzy matches rather than guessing; this is how a
    person overrides it once they have looked. Recorded as `manual` so a lead
    sourced this way can be told apart from one the resolver was sure about.
    """
    from intentdesk.services import companies

    row = await db.fetchrow("SELECT * FROM organisers WHERE id = $1", organiser_id)
    if row is None:
        raise HTTPException(status_code=404, detail="No such organiser")
    if not row["resolved_domain"]:
        raise HTTPException(
            status_code=422,
            detail="No domain was found for this organiser, so there is nothing "
                   "to promote. Resolve it first or reject it.",
        )

    company = await companies.upsert(
        name=row["name"], domain=row["resolved_domain"],
        vendor=row["platform"], city=row["city"], country="IN",
    )
    await db.execute(
        "UPDATE companies SET phone = coalesce(phone, $2), discovered_via = $3,"
        " match_confidence = 'manual' WHERE id = $1",
        company["id"], row["resolved_phone"], row["source"],
    )
    await db.execute(
        "UPDATE organisers SET status='resolved', company_id=$2,"
        " resolve_confidence='manual', updated_at=now() WHERE id=$1",
        organiser_id, company["id"],
    )
    return {"organiser_id": organiser_id, "company": dict(company)}


@app.post("/api/organisers/{organiser_id}/reject")
async def api_reject_organiser(
    organiser_id: int,
    user: dict = Depends(require_admin),
):
    """Dismiss a match so a rescan does not resurface it."""
    row = await db.fetchrow(
        "UPDATE organisers SET status='rejected', updated_at=now() "
        "WHERE id=$1 RETURNING id, name",
        organiser_id,
    )
    if row is None:
        raise HTTPException(status_code=404, detail="No such organiser")
    return dict(row)


@app.get("/api/sources")
async def api_sources(user: dict = Depends(require_user)):
    """Registry state for the source tabs.

    Returned rather than hardcoded in the UI so a tab can say *why* it is empty
    — needs credentials, known broken, not built — instead of showing zero rows
    and leaving the reader to guess whether that is a bug.
    """
    from intentdesk.collectors import availability

    return availability()


@app.get("/api/signals/counts")
async def api_signal_counts(days: int = 30, user: dict = Depends(require_user)):
    """Feed header: how much arrived, how much matched, and the split by kind."""
    return await signals.counts(days=days)


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
@app.post("/api/signals/classify")
async def api_classify_signals(
    limit: int = Query(25, le=200), user: dict = Depends(require_user)
):
    """Read the complaint out of stored reviews: category, core complaint, severity.

    Every draft is now written about the complaint pattern for the platform a
    company runs, and that pattern is computed from these columns — so a review
    left unclassified contributes nothing to any draft. Billed in LLM tokens, not
    provider credits.
    """
    from intentdesk.services import drafting

    return await drafting.classify_pending(limit)


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
    return await scan.run(competitor, free_only=free_only,
                          actor_email=user.get("email"))


# ------------------------------------------------ on-demand paid collection
#
# The per-row and per-source buttons. Separate from /api/scan on purpose: this one
# names a single source, quotes its price first, checks the cap, and attributes
# the spend to whoever clicked. /api/scan is the sweep.
@app.get("/api/collect/estimate")
async def api_collect_estimate(
    source: str,
    competitor: Optional[str] = None,
    n: int = Query(20, ge=1, le=500),
    user: dict = Depends(require_user),
):
    """What a collection run will cost, before it is started.

    Also answers whether it is *allowed* — a source can refuse a specific brand
    (Trustpilot does, for consumer marketplaces) and the button should render
    disabled with that reason rather than failing on click.
    """
    from intentdesk.collectors import PRICED_ACTION, get as get_collector
    from intentdesk.collectors.organisers import discovery_class
    from intentdesk.services import spend

    coll = get_collector(source)
    if coll is None:
        # Discovery sources are advertised by /api/sources, so the screen prices
        # every row it renders. 404-ing here made three of those rows quote
        # nothing and their buttons fail on click.
        if discovery_class(source) is not None:
            return {
                "source": source,
                "competitor": competitor,
                "estimate": spend.estimate("discover_organisers", n),
                "spend": await spend.month_to_date(),
                "blocked": None,
                "allowed": True,
            }
        raise HTTPException(status_code=404, detail=f"No collector named {source!r}")

    action = PRICED_ACTION.get(source, f"collect_{source}")
    est = spend.estimate(action, n)

    blocked = None
    if not coll.available():
        blocked = (coll.known_broken
                   or ("missing credentials: " + ", ".join(coll.missing_credentials())
                       if coll.missing_credentials() else "not implemented"))
    elif competitor and hasattr(coll, "check"):
        blocked = coll.check(competitor)

    state = await spend.month_to_date()
    return {
        "source": source,
        "competitor": competitor,
        "estimate": est,
        "spend": state,
        "blocked": blocked,
        "allowed": blocked is None and not (state["exhausted"] and not est["free"]),
    }


class CollectBody(BaseModel):
    source: str
    competitor: Optional[str] = None
    # Deliberately explicit rather than inferred from the estimate call: a client
    # that quoted one figure and then ran a bigger job would make the quote a lie.
    override_cap: bool = False


@app.post("/api/collect")
async def api_collect(body: CollectBody, user: dict = Depends(require_admin)):
    """Run one source, now. **Costs money for paid sources.**

    Admin-only, and the cap is checked before the collector starts. `override_cap`
    is recorded in the ledger, so passing the cap deliberately is visible after
    the fact rather than indistinguishable from a cap that never applied.
    """
    from intentdesk.collectors import PRICED_ACTION, get as get_collector
    from intentdesk.collectors import organisers
    from intentdesk.collectors.organisers import discovery_class
    from intentdesk.services import spend

    coll = get_collector(body.source)
    if coll is None:
        # A discovery source finds companies rather than evidence, so it does not
        # go through scan.run() — but the Sources screen offers it a Run button
        # like any other row, and that button has to do the right thing.
        if discovery_class(body.source) is not None:
            result = await organisers.discover(limit=100, source=body.source)
            per = result["by_source"].get(body.source, {})
            return {
                "collectors_ran": [{
                    "collector": body.source,
                    "found": per.get("seen", 0),
                    "new": per.get("new", 0),
                    "cost_usd": 0.0,
                }],
                "collectors_skipped": [],
                "cost_usd": 0.0,
                "discovery": result,
            }
        raise HTTPException(status_code=404, detail=f"No collector named {body.source!r}")

    if body.competitor and hasattr(coll, "check"):
        reason = coll.check(body.competitor)
        if reason:
            # 422 rather than 402: the request is well-formed and the refusal is
            # about what the data would be worth, not about money.
            raise HTTPException(status_code=422, detail=reason)

    action = PRICED_ACTION.get(body.source, f"collect_{body.source}")
    try:
        await spend.guard(action, 1, override=body.override_cap)
    except spend.SpendRefused as exc:
        raise HTTPException(status_code=402, detail=exc.as_dict()) from exc

    return await scan.run(
        body.competitor, sources=[body.source], actor_email=user.get("email")
    )


# ------------------------------------------------------- per-signal enrichment
@app.get("/api/signals/{signal_id}/identity")
async def api_signal_identity(signal_id: int, user: dict = Depends(require_user)):
    """Can this reviewer be resolved, at what tier, and what would it cost? Free.

    This is what decides whether the row's Enrich button renders enabled. A `low`
    verdict here is why nothing is spent discovering that "Irfan M." has no
    surname.
    """
    from intentdesk.services import identity

    try:
        return await identity.assess(signal_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/signals/{signal_id}/enrich-reviewer")
async def api_enrich_reviewer(
    signal_id: int,
    override_cap: bool = False,
    user: dict = Depends(require_admin),
):
    """Resolve who wrote a review. **Paid**, cached, and refused at `low`.

    Admin-only because the subject is a person rather than a business.
    """
    from intentdesk.services import identity, spend

    try:
        return await identity.resolve(
            signal_id, actor_email=user.get("email"), override=override_cap
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except spend.SpendRefused as exc:
        raise HTTPException(status_code=402, detail=exc.as_dict()) from exc
    except RuntimeError as exc:
        # Apollo 403 (still on the free plan) and 429 land here. 502 rather than
        # 500: the fault is upstream and the message says which upstream state it
        # is, because "no person found" and "your plan blocks this endpoint" need
        # completely different fixes.
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/api/signals/{signal_id}/enrich-company")
async def api_enrich_signal_company(signal_id: int, user: dict = Depends(require_user)):
    """Enrich the company a signal is matched to. Free — Apollo's
    `organizations/enrich` works on the free plan."""
    from intentdesk.services import enrichment

    company_id = await db.fetchval(
        "SELECT company_id FROM signals WHERE id = $1", signal_id
    )
    if company_id is None:
        raise HTTPException(
            status_code=422,
            detail="This signal is not matched to a company, so there is nothing "
                   "to enrich. Most reviews are unmatched: the sites publish no "
                   "employer.",
        )
    try:
        return await enrichment.enrich_company(company_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except enrichment.EnrichmentUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get("/api/identity/pending")
async def api_identity_pending(
    limit: int = Query(50, le=200), user: dict = Depends(require_user)
):
    """Named reviewers with no identity resolved yet, best candidates first."""
    from intentdesk.services import identity

    return await identity.pending(limit)


@app.get("/api/identity/stats")
async def api_identity_stats(user: dict = Depends(require_user)):
    from intentdesk.services import identity

    return await identity.stats()


# --------------------------------------------------------------------- spend
@app.get("/api/spend")
async def api_spend(month: Optional[str] = None, user: dict = Depends(require_user)):
    """This month against the cap, split by provider, action and user."""
    from intentdesk.services import spend

    try:
        return await spend.report(month)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


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
async def cron_scan(competitor: Optional[str] = None):
    """The scheduled scan. **Free collectors only, and not negotiable.**

    `free_only` used to be a query parameter here, which meant the difference
    between a free nightly scan and an unattended paid one was a flag in an n8n
    node that nobody would look at again. Paid collection belongs on a button
    with its price on it — see POST /api/collect.
    """
    return await scan.run(competitor, free_only=True, actor_email="cron")


@cron.post("/discover")
async def cron_discover(limit: int = 500):
    """Walk the organiser sitemaps on the schedule.

    Discovery is free — a sitemap fetch, no actor and no credits — so by the same
    rule that keeps paid collectors off this router, it belongs *on* it. It was
    reachable only through POST /api/discover, which needs a browser session,
    so the organiser pool grew only when somebody remembered to click. The
    expensive half stays a click: resolving a name into a domain bills per row
    and lives at POST /api/resolve.
    """
    from intentdesk.collectors import organisers

    return await organisers.discover(limit=limit)


@cron.post("/enrich")
async def cron_enrich(limit: int = 25):
    from intentdesk.services import enrichment

    return await enrichment.enrich_pending(limit)


@cron.post("/classify")
async def cron_classify(limit: int = 25):
    """Must run before /draft, not after.

    Drafting reads the complaint pattern these columns hold. Classify second and
    every draft that night is written from yesterday's evidence.
    """
    from intentdesk.services import drafting

    return await drafting.classify_pending(limit)


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


@cron.post("/push-sheet")
async def cron_push_sheet():
    """Write the queue into the configured Google Sheet.

    Free — the Sheets API costs nothing — so it belongs on the schedule by the
    same rule as /discover. It replaces the public CSV route the sheet used to
    pull with IMPORTDATA, which had to be world-readable because IMPORTDATA
    cannot send an Authorization header.
    """
    from intentdesk.services import sheets

    try:
        return await sheets.push_leads()
    except sheets.SheetsUnavailable as exc:
        # 503 with the reason, not a 200 with an empty result. A push that
        # silently does nothing is indistinguishable from a quiet week.
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@cron.get("/push-sheet/probe")
async def cron_push_sheet_probe():
    """Whether the Sheets push would work, and where it breaks if not."""
    from intentdesk.services import sheets

    return await sheets.probe()


@cron.get("/leads")
async def cron_leads(
    status: Optional[str] = None,
    heat: Optional[str] = None,
    limit: int = Query(500, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """Leads as flat JSON rows, for the Google Sheets sync.

    On the cron router rather than `/api` because the caller is n8n, which has no
    browser session — every `/api/*` route is cookie-gated, which is why a
    scheduled spreadsheet sync had nowhere to read from. Free and read-only: it
    returns stored rows and collects nothing, so it belongs on a schedule by the
    same rule that puts `/discover` there.

    Paged deliberately. See `export.leads_for_sheet` — Cloudflare kills a request
    at ~100s and reports the failure as a failed node.
    """
    from intentdesk.services import export

    return await export.leads_for_sheet(
        status=status, heat=heat, limit=limit, offset=offset
    )


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
    try:
        body = await export.leads_csv(status=status, heat=heat)
    except export.NothingToExport as exc:
        # 409 rather than 404: the endpoint is fine and the queue is a real
        # resource, it just has nothing in it. A downloaded file containing only
        # headers is the outcome this exists to prevent.
        raise HTTPException(status_code=409, detail=exc.reason) from exc
    return Response(
        content=body.encode("utf-8"),
        # charset declared explicitly; the BOM handles Excel, this handles
        # anything that reads the header instead of sniffing.
        media_type="text/csv; charset=utf-8",
        headers={"content-disposition": 'attachment; filename="intent-desk-leads.csv"'},
    )


@app.get("/api/export/leads.xlsx")
async def api_export_xlsx(
    status: Optional[str] = None,
    heat: Optional[str] = None,
    user: dict = Depends(require_user),
):
    """The same queue as a workbook — frozen header, filters, sortable Score."""
    try:
        body = await export.leads_xlsx(status=status, heat=heat)
    except export.NothingToExport as exc:
        raise HTTPException(status_code=409, detail=exc.reason) from exc
    return Response(
        content=body,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"content-disposition": 'attachment; filename="intent-desk-leads.xlsx"'},
    )


# ----------------------------------------------------- review period export
#
# Reads stored rows and never collects. A date range is a cheap thing to type and
# the sources behind these rows bill per run, so a fetch wired to a date picker
# would turn a typo into a charge.
@app.get("/api/export/reviews")
async def api_export_reviews(
    since: Optional[datetime] = Query(None, alias="from"),
    until: Optional[datetime] = Query(None, alias="to"),
    group: str = Query("month", pattern="^(month|year)$"),
    platform: Optional[str] = None,
    source: Optional[str] = Query(None, alias="source_site"),
    rating_lte: Optional[float] = None,
    format: str = Query("xlsx", pattern="^(csv|xlsx)$"),
    user: dict = Depends(require_user),
):
    """Collected reviews for a period, grouped by month or year.

    The workbook carries a Summary sheet first — per-period counts, average
    rating, how many said outright that they switched — then every row behind it.
    """
    kwargs = dict(since=since, until=until, platform=platform,
                  source_site=source, rating_lte=rating_lte, group=group)
    stamp = (since.date().isoformat() if since else "all")

    try:
        if format == "csv":
            body = await export.reviews_csv(**kwargs)
            return Response(
                content=body.encode("utf-8"),
                media_type="text/csv; charset=utf-8",
                headers={"content-disposition":
                         f'attachment; filename="intent-desk-reviews-{stamp}.csv"'},
            )
        blob = await export.reviews_xlsx(**kwargs)
    except export.NothingToExport as exc:
        raise HTTPException(status_code=409, detail=exc.reason) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return Response(
        content=blob,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"content-disposition":
                 f'attachment; filename="intent-desk-reviews-{stamp}.xlsx"'},
    )


# ------------------------------------------------------ MCP over HTTP
# Mounted here rather than on its own subdomain: no DNS record, no second
# container, and TLS is already terminated for this host. Must be mounted
# before the catch-all static mount below, since routes match in order.
app.mount("/mcp", BearerAuthASGI(_mcp_asgi, settings.mcp_bearer_token))


# ----------------------------------------------- static dashboard bundle
# Registered last on purpose: this is a catch-all. `html=True` still serves
# index.html for unmatched paths, which is what keeps /assets/* working — the
# routes above claim "/" and "/app" before it ever sees them.
if _DIST.is_dir():
    app.mount("/", StaticFiles(directory=str(_DIST), html=True), name="dashboard")
