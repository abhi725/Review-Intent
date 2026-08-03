"""The authenticated Google Sheets push.

Written after three other routes failed for this account — OAuth2, an Apps Script,
and a service-account credential inside n8n — and after a public CSV route that
worked but had to be world-readable, because IMPORTDATA cannot send an
Authorization header. Pushing puts the credential on this side and exposes
nothing.

The properties worth holding still:

* **No new dependency.** The assertion is signed with `authlib.jose`, a pinned
  first-class requirement. PyJWT is the obvious alternative and is **absent from
  the container** while present in the dev venv, so code written against it passes
  locally and fails in production.
* **Unconfigured is reported, never silent.** A push that quietly writes nothing
  looks exactly like a week with no leads.
* **RAW input.** `USER_ENTERED` lets Sheets reinterpret as it writes, which turns
  a phone number into a formula error.
* **Stale rows are cleared.** A queue that shrinks must not leave orphans behind
  that read as current leads.
"""

import base64
import json

import pytest

from intentdesk.config import settings
from intentdesk.services import sheets

def _throwaway_key() -> str:
    """A real RSA key, generated here and never stored.

    A placeholder string would fail at PEM parsing, which happens *before* the
    token request — so a test using one proves nothing about the request and
    reports a signing error as though it were the behaviour under test.
    """
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()


FAKE_SA = {
    "client_email": "svc@example.iam.gserviceaccount.com",
    "token_uri": "https://oauth2.googleapis.com/token",
    "private_key": _throwaway_key(),
}
FAKE_B64 = base64.b64encode(json.dumps(FAKE_SA).encode()).decode()


def _code_only(obj) -> str:
    """Source with comments and docstrings removed.

    Assertions about what the code does must not be satisfied — or broken — by
    prose that explains the rule. The comment above the RAW parameter names
    USER_ENTERED in order to say why it is not used, and a naive substring check
    reads that as a violation.
    """
    import inspect
    import re

    source = inspect.getsource(obj)
    source = re.sub(r'"""[\s\S]*?"""', "", source)
    return re.sub(r"#[^\n]*", "", source)


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setattr(settings, "google_sheets_sa_json", FAKE_B64)
    monkeypatch.setattr(settings, "google_sheets_id", "sheet-123")


@pytest.fixture(autouse=True)
def clear_token_cache():
    sheets._token_cache.update({"token": None, "expires_at": 0.0})
    yield
    sheets._token_cache.update({"token": None, "expires_at": 0.0})


# ------------------------------------------------------------- configuration
def test_unconfigured_is_unavailable(monkeypatch):
    monkeypatch.setattr(settings, "google_sheets_sa_json", "")
    monkeypatch.setattr(settings, "google_sheets_id", "")
    assert sheets.available() is False
    assert sheets.credentials() is None


def test_key_without_sheet_id_is_unavailable(monkeypatch):
    monkeypatch.setattr(settings, "google_sheets_sa_json", FAKE_B64)
    monkeypatch.setattr(settings, "google_sheets_id", "")
    assert sheets.available() is False
    assert "GOOGLE_SHEETS_ID" in sheets._reason_unavailable()


def test_sheet_id_without_key_is_unavailable(monkeypatch):
    monkeypatch.setattr(settings, "google_sheets_sa_json", "")
    monkeypatch.setattr(settings, "google_sheets_id", "sheet-123")
    assert sheets.available() is False
    assert "GOOGLE_SHEETS_SA_JSON" in sheets._reason_unavailable()


def test_configured_is_available(configured):
    assert sheets.available() is True
    assert sheets.credentials()["client_email"] == FAKE_SA["client_email"]


def test_malformed_key_says_so_rather_than_looking_unconfigured(monkeypatch):
    """A truncated paste is a different problem from an empty setting, and the
    difference is what someone needs to be told."""
    monkeypatch.setattr(settings, "google_sheets_sa_json", "this-is-not-base64-json")
    monkeypatch.setattr(settings, "google_sheets_id", "sheet-123")
    with pytest.raises(sheets.SheetsUnavailable, match="base64"):
        sheets.credentials()
    # available() must not raise — it is called on paths that only want a bool.
    assert sheets.available() is False


def test_push_refuses_when_unconfigured(monkeypatch):
    import asyncio

    monkeypatch.setattr(settings, "google_sheets_sa_json", "")
    monkeypatch.setattr(settings, "google_sheets_id", "")
    with pytest.raises(sheets.SheetsUnavailable):
        asyncio.run(sheets.push_leads())


# ------------------------------------------------------------ implementation
def test_signing_uses_authlib_not_pyjwt():
    """PyJWT is missing from the container while installed in the dev venv, so
    depending on it is a bug that only appears in production."""
    code = _code_only(sheets)
    assert "authlib.jose" in code
    # A bare `import jwt` at the start of a line is PyJWT. The authlib import is
    # `from authlib.jose import jwt as ajwt`, which contains the same substring.
    assert "\nimport jwt" not in code, "PyJWT is not available in the container"


def test_writes_are_raw_not_user_entered():
    """USER_ENTERED makes Sheets reinterpret values: "+91 99582 65656" becomes a
    formula error and "1/2 Ton Studio" becomes a date."""
    code = _code_only(sheets.push_leads)
    assert '"RAW"' in code or "'RAW'" in code
    assert "USER_ENTERED" not in code


def test_stale_rows_are_cleared():
    import inspect

    source = inspect.getsource(sheets.push_leads)
    assert ":clear" in source or "values/" in source
    assert "first_stale" in source, (
        "a shrinking queue would leave orphan rows that read as current leads"
    )


def test_tab_title_is_read_not_assumed():
    """Ranges are addressed by title and the default is not always Sheet1; a
    renamed tab would make every write target a nonexistent range."""
    import inspect

    assert "Sheet1" not in inspect.getsource(sheets.push_leads)
    assert "_first_tab_title" in inspect.getsource(sheets.push_leads)


# ------------------------------------------------------------- column labels
@pytest.mark.parametrize("n,expected", [
    (1, "A"), (2, "B"), (26, "Z"), (27, "AA"), (28, "AB"),
    (52, "AZ"), (53, "BA"), (19, "S"),
])
def test_column_letters(n, expected):
    """The clear range spans the written width. Hard-coding today's 19 columns
    would silently stop clearing the last one the day a column is added."""
    assert sheets._col(n) == expected


# ------------------------------------------------------------- token caching
def test_token_is_reused_while_valid(configured, monkeypatch):
    import asyncio
    import time

    sheets._token_cache.update({"token": "cached-token",
                                "expires_at": time.time() + 3600})

    class Boom:
        async def post(self, *a, **k):
            raise AssertionError("re-minted a token that was still valid")

    got = asyncio.run(sheets._access_token(Boom()))
    assert got == "cached-token"


def test_token_is_reminted_near_expiry(configured):
    """A token expiring between the check and the call fails the whole push, so
    there is deliberate headroom."""
    import asyncio
    import time

    # Inside the skew window: still unexpired, but too close to rely on.
    sheets._token_cache.update({"token": "about-to-expire",
                                "expires_at": time.time() + 5})

    class Reminted:
        """Stands in for the token endpoint, and records that it was called."""

        called = False

        async def post(self, url, data=None, **k):
            Reminted.called = True
            assert data["grant_type"].endswith("jwt-bearer")
            assert data["assertion"], "an assertion must be signed and sent"

            class R:
                status_code = 200

                @staticmethod
                def json():
                    return {"access_token": "fresh-token", "expires_in": 3600}

            return R()

    got = asyncio.run(sheets._access_token(Reminted()))
    assert Reminted.called, "a token inside the skew window must be re-minted"
    assert got == "fresh-token"


# ------------------------------------------------------------------ the cron
def test_push_sheet_is_on_the_cron_allow_list():
    """It is free — the Sheets API costs nothing — so it belongs on a schedule,
    and test_cron_surface fails in both directions."""
    from tests.test_cron_surface import SCHEDULABLE

    assert "/push-sheet" in SCHEDULABLE
