"""Push the lead queue into a Google Sheet, authenticated.

This replaces the public CSV the sheet used to pull with IMPORTDATA. That route
worked but had to be world-readable — IMPORTDATA cannot send an Authorization
header, so the secret was the URL and anyone holding it could read the queue.
Pushing inverts the direction: the credential lives here, the sheet is shared with
one service account, and nothing is public.

**No new dependency.** The JWT is signed with `authlib.jose`, which is already a
pinned first-class requirement (Authlib backs the Google sign-in). `google-auth`
would pull a large tree onto a RAM-tight VM for one signature, and PyJWT — the
obvious alternative — is **absent from the container** even though it is installed
in the dev venv, so code written against it passes locally and fails in
production. Checked before writing this, not after.

The service account needs two things that fail differently and are worth telling
apart: the Sheets API enabled on its project (token exchange succeeds, the API
call 403s saying the API is disabled), and the spreadsheet shared with its address
as Editor (read works, write 403s). `probe()` reports which.
"""

import base64
import json
import logging
import time
from typing import Optional

import httpx
from authlib.jose import jwt as ajwt

from intentdesk.config import settings
from intentdesk.services import export

log = logging.getLogger(__name__)

SCOPE = "https://www.googleapis.com/auth/spreadsheets"
SHEETS_API = "https://sheets.googleapis.com/v4/spreadsheets"
TIMEOUT = 60.0

# Google issues a one-hour token. Re-minting per push would be a needless round
# trip, so it is cached — but with a minute of headroom, because a token that
# expires between the check and the call fails the whole push.
_EXPIRY_SKEW_S = 60
_token_cache: dict = {"token": None, "expires_at": 0.0}


class SheetsUnavailable(RuntimeError):
    """Raised with the reason, rather than returning an empty result.

    A push that silently does nothing looks exactly like a week with no new
    leads, which is the failure mode this codebase keeps having to design out.
    """


def credentials() -> Optional[dict]:
    """The service account, or None when not configured.

    Stored base64 in one setting rather than as separate email and key fields: a
    PEM private key spread across a .env file is where newline handling goes
    wrong, and one opaque value cannot be half-configured.
    """
    raw = settings.google_sheets_sa_json or ""
    if not raw:
        return None
    try:
        return json.loads(base64.b64decode(raw))
    except (ValueError, json.JSONDecodeError) as exc:
        raise SheetsUnavailable(
            f"GOOGLE_SHEETS_SA_JSON is set but is not base64-encoded JSON: {exc}"
        ) from exc


def available() -> bool:
    """Whether a push could run at all. Cheap, and does no network work."""
    try:
        creds = credentials()
    except SheetsUnavailable:
        return False
    return bool(creds and settings.google_sheets_id)


def _reason_unavailable() -> str:
    if not (settings.google_sheets_sa_json or ""):
        return ("GOOGLE_SHEETS_SA_JSON is not set — base64 the service account "
                "JSON key into it")
    if not settings.google_sheets_id:
        return "GOOGLE_SHEETS_ID is not set — the spreadsheet to write to"
    return "unknown"


async def _access_token(client: httpx.AsyncClient) -> str:
    now = time.time()
    if _token_cache["token"] and _token_cache["expires_at"] > now + _EXPIRY_SKEW_S:
        return _token_cache["token"]

    creds = credentials()
    if creds is None:
        raise SheetsUnavailable(_reason_unavailable())

    issued = int(now)
    assertion = ajwt.encode(
        {"alg": "RS256", "typ": "JWT"},
        {
            "iss": creds["client_email"],
            "scope": SCOPE,
            "aud": creds["token_uri"],
            "iat": issued,
            "exp": issued + 3600,
        },
        creds["private_key"],
    )
    if isinstance(assertion, bytes):
        assertion = assertion.decode()

    r = await client.post(creds["token_uri"], data={
        "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
        "assertion": assertion,
    })
    if r.status_code != 200:
        raise SheetsUnavailable(
            f"Google refused the service account assertion ({r.status_code}): "
            f"{r.text[:300]}"
        )

    body = r.json()
    _token_cache["token"] = body["access_token"]
    _token_cache["expires_at"] = now + float(body.get("expires_in", 3600))
    return _token_cache["token"]


async def _first_tab_title(client: httpx.AsyncClient, token: str,
                           sheet_id: str) -> str:
    """The first tab's title, read rather than assumed.

    Ranges are addressed by title, and the default is not always "Sheet1" — a
    renamed tab would make every write land in a range that does not exist, which
    the API reports as a parse error rather than as a missing sheet.
    """
    r = await client.get(
        f"{SHEETS_API}/{sheet_id}",
        headers={"Authorization": f"Bearer {token}"},
        params={"fields": "sheets.properties.title,sheets.properties.gridProperties"},
    )
    if r.status_code == 403:
        raise SheetsUnavailable(
            "403 reading the spreadsheet. Either the Sheets API is not enabled on "
            "the service account's project, or the sheet is not shared with its "
            f"address. Google said: {r.text[:200]}"
        )
    if r.status_code == 404:
        raise SheetsUnavailable(
            f"no spreadsheet with id {sheet_id!r} — check GOOGLE_SHEETS_ID"
        )
    if r.status_code != 200:
        raise SheetsUnavailable(f"reading the spreadsheet failed: {r.status_code} "
                                f"{r.text[:200]}")

    tabs = r.json().get("sheets") or []
    if not tabs:
        raise SheetsUnavailable("the spreadsheet has no tabs")
    return tabs[0]["properties"]["title"]


def _quote(title: str) -> str:
    """A tab title inside an A1 range. Titles with spaces or quotes need it."""
    return "'" + title.replace("'", "''") + "'"


async def push_leads(status: Optional[str] = None,
                     heat: Optional[str] = None) -> dict:
    """Write the queue into the sheet, replacing what is there.

    A full replace rather than an upsert. The sheet is a mirror of the queue, and
    a replace cannot drift: a row deleted here disappears there, and a lead whose
    score or status changed does not need matching. It writes only the columns it
    owns, so anything a person adds to the right of them survives.
    """
    if not available():
        raise SheetsUnavailable(_reason_unavailable())

    page = await export.leads_for_sheet(status=status, heat=heat, limit=500)
    rows = page["rows"]
    if not rows:
        return {"pushed": 0, "note": "no leads to write; the sheet was left alone"}

    headers = list(rows[0].keys())
    values = [headers]
    for row in rows:
        values.append([row.get(h, "") for h in headers])

    sheet_id = settings.google_sheets_id
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        token = await _access_token(client)
        tab = await _first_tab_title(client, token, sheet_id)
        auth = {"Authorization": f"Bearer {token}"}
        quoted = _quote(tab)

        # RAW, not USER_ENTERED. Sheets would otherwise interpret as it goes:
        # "+91 99582 65656" becomes a formula error, and a company named
        # "1/2 Ton Studio" becomes a date.
        r = await client.put(
            f"{SHEETS_API}/{sheet_id}/values/{quoted}!A1",
            headers=auth,
            params={"valueInputOption": "RAW"},
            json={"values": values},
        )
        if r.status_code == 403:
            raise SheetsUnavailable(
                "403 writing to the spreadsheet — it is shared with the service "
                "account as Viewer rather than Editor"
            )
        if r.status_code != 200:
            raise SheetsUnavailable(f"writing failed: {r.status_code} "
                                    f"{r.text[:300]}")
        updated = r.json().get("updatedCells", 0)

        # Clear whatever the previous, longer run left behind. Without this a queue
        # that shrinks leaves orphan rows that read as current leads.
        first_stale = len(values) + 1
        cleared = await client.post(
            f"{SHEETS_API}/{sheet_id}/values/"
            f"{quoted}!A{first_stale}:{_col(len(headers))}",
            headers=auth, json={},
        )
        if cleared.status_code not in (200, 400):
            log.warning("could not clear stale rows: %s %s",
                        cleared.status_code, cleared.text[:200])

    return {
        "pushed": len(rows),
        "cells": updated,
        "tab": tab,
        "columns": len(headers),
        "cleared_from_row": first_stale,
    }


def _col(n: int) -> str:
    """1 -> A, 26 -> Z, 27 -> AA. The queue has 19 columns today, but a range
    hard-coded to the current width silently stops clearing the last column the
    day one is added."""
    out = ""
    while n:
        n, rem = divmod(n - 1, 26)
        out = chr(65 + rem) + out
    return out


async def probe() -> dict:
    """Check the whole path without writing lead data. For diagnosis."""
    if not available():
        return {"ok": False, "stage": "config", "detail": _reason_unavailable()}
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            token = await _access_token(client)
            tab = await _first_tab_title(client, token, settings.google_sheets_id)
    except SheetsUnavailable as exc:
        return {"ok": False, "stage": "google", "detail": str(exc)}
    creds = credentials() or {}
    return {
        "ok": True,
        "service_account": creds.get("client_email"),
        "spreadsheet": settings.google_sheets_id,
        "first_tab": tab,
        "token_cached_until": _token_cache["expires_at"],
    }
