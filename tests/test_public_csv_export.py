"""The one deliberately public data path, and the rules it has to keep.

`/export/leads-<token>.csv` is unauthenticated on purpose. Google Sheets'
`IMPORTDATA` cannot send an Authorization header, so a bearer-token route is
simply unreachable from a spreadsheet formula — the secret has to be in the URL.
The user accepted that trade-off explicitly, after OAuth2, service-account and
Apps Script routes all failed.

Accepting it does not mean being careless about it. Four properties keep this from
becoming a leak nobody decided on:

* **Off by default.** No token, no route. A public path that exposes the lead
  queue must be switched on deliberately and never inherited from a default.
* **A short token is treated as no token.** The secret is the only thing between
  these rows and the open internet, so its length is checked rather than trusted.
* **Constant-time comparison.** `==` leaks how long a matching prefix was, which
  turns guessing from infeasible into a few thousand requests.
* **The token is never the thing that is logged or echoed.** Nothing here returns
  it, and a wrong guess is answered as though the route does not exist.
"""

import pytest

from intentdesk.config import settings
from intentdesk.services import export

GOOD = "T" * 43  # what secrets.token_urlsafe(32) produces


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setattr(settings, "sheet_export_token", GOOD)


@pytest.fixture
def unset(monkeypatch):
    monkeypatch.setattr(settings, "sheet_export_token", "")


# ------------------------------------------------------------- off by default
def test_disabled_when_no_token(unset):
    assert export.sheet_export_enabled() is False


def test_no_token_rejects_everything(unset):
    """Including an empty guess, which is what a bare /export/leads-.csv sends."""
    for guess in ("", GOOD, "anything"):
        assert export.sheet_export_token_ok(guess) is False


@pytest.mark.parametrize("token", ["", "x", "short", "a" * 23])
def test_a_short_token_is_no_token(monkeypatch, token):
    monkeypatch.setattr(settings, "sheet_export_token", token)
    assert export.sheet_export_enabled() is False, (
        f"{len(token)}-character token accepted — brute force against a path that "
        "answers 404 for wrong guesses and 200 for the right one is cheap"
    )
    assert export.sheet_export_token_ok(token) is False


def test_the_boundary_length_is_enforced_both_ways(monkeypatch):
    at_limit = "a" * export.EXPORT_TOKEN_MIN_LEN
    monkeypatch.setattr(settings, "sheet_export_token", at_limit)
    assert export.sheet_export_enabled() is True

    monkeypatch.setattr(settings, "sheet_export_token", at_limit[:-1])
    assert export.sheet_export_enabled() is False


# ------------------------------------------------------------- matching rules
def test_correct_token_is_accepted(configured):
    assert export.sheet_export_enabled() is True
    assert export.sheet_export_token_ok(GOOD) is True


@pytest.mark.parametrize("guess", [
    "",
    "wrong",
    GOOD[:-1],            # right prefix, one character short
    GOOD[:-1] + "X",      # right length, last character wrong
    GOOD + "X",           # right token with something appended
    GOOD.lower(),         # case must matter
    " " + GOOD,           # no trimming
    GOOD + " ",
])
def test_near_misses_are_rejected(configured, guess):
    assert export.sheet_export_token_ok(guess) is False


def test_comparison_is_constant_time(configured):
    """A prefix match must cost the same as no match at all.

    Asserted on the implementation rather than by timing, because a timing test
    is flaky on a shared box and would either be useless or fail at random. What
    matters is that `hmac.compare_digest` is what does the comparing.
    """
    import inspect
    import re

    source = inspect.getsource(export.sheet_export_token_ok)
    # Strip the docstring before looking for `==`. The docstring explains why
    # compare_digest is used and names `==` while doing so, and `inspect.getdoc`
    # returns it dedented, so it cannot simply be subtracted from the source.
    body = re.sub(r'"""[\s\S]*?"""', "", source)
    assert "compare_digest" in body, "must not compare the token with =="
    assert "==" not in body.replace("!=", ""), (
        "an equality comparison on the token leaks its prefix through timing"
    )


def test_none_is_handled(configured):
    """The path parameter can arrive empty; it must not raise."""
    assert export.sheet_export_token_ok(None) is False


# ------------------------------------------- the route is declared and guarded
@pytest.mark.parametrize("path", ["/export/leads/{token}",
                                  "/export/leads-{token}.csv"])
def test_route_exists_and_is_public(path):
    """Both must be registered, and both ahead of the StaticFiles catch-all —
    the mount at "/" swallows anything declared after it."""
    from intentdesk.api.app import app

    paths = [getattr(r, "path", None) for r in app.routes]
    assert path in paths

    csv_at = paths.index(path)
    # Found by name, not by path: Starlette normalises the mount at "/" to an
    # empty path, and the landing route genuinely sits at "/", so matching on the
    # path finds the wrong thing.
    mount_at = next(i for i, r in enumerate(app.routes)
                    if getattr(r, "name", None) == "dashboard")
    assert csv_at < mount_at, (
        "declared after the catch-all mount, so the dashboard bundle would answer "
        "this URL instead"
    )


def test_the_uncached_path_asks_for_no_caching():
    """Cloudflare caches by file extension, so the extensionless route is the one
    whose Cache-Control actually survives — measured: the `.csv` URL came back
    max-age=14400 against our max-age=300. A stale edge copy of a revoked token
    would keep serving after rotation."""
    import inspect

    from intentdesk.api.app import _public_leads_csv

    source = inspect.getsource(_public_leads_csv)
    assert "no-store" in source, (
        "the uncached variant must send no-store, or rotation is not immediate"
    )


def test_robots_disallows_the_export():
    """Unguessable is not the same as unindexable: a URL can leak through a
    pasted link or a referrer header."""
    import asyncio

    from intentdesk.api.app import robots

    body = asyncio.run(robots()).body.decode()
    assert "Disallow: /export/" in body


# ------------------------------------------------------------------- no BOM
def test_public_export_sends_no_byte_order_mark():
    """IMPORTDATA puts the first line straight into cells, so a BOM becomes an
    invisible character on the front of the first heading — a header that looks
    correct, does not compare equal to "Company", and hides the reason why.

    The browser download keeps its BOM, because Excel on Windows needs it.
    """
    import inspect

    from intentdesk.api.app import _public_leads_csv

    assert "bom=False" in inspect.getsource(_public_leads_csv), (
        "the public CSV must be requested without a BOM"
    )


def test_leads_csv_bom_is_optional_and_defaults_on():
    import inspect

    from intentdesk.services import export

    sig = inspect.signature(export.leads_csv)
    assert "bom" in sig.parameters
    assert sig.parameters["bom"].default is True, (
        "the download path must keep its BOM by default, or Excel mangles "
        "non-ASCII company names"
    )
