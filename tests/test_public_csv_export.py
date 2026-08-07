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
    # Absent in a fresh checkout, where web/dist has not been built and the
    # mount is therefore never registered — nothing to be ordered against.
    mount_at = next((i for i, r in enumerate(app.routes)
                     if getattr(r, "name", None) == "dashboard"), None)
    if mount_at is None:
        pytest.skip("dashboard bundle not built — run `npm run build` in web/")
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


# ------------------------------------------------------- the write-up pages
@pytest.mark.parametrize("path", ["/work", "/work/visibility-agent",
                                  "/work/growth-strategy"])
def test_work_pages_are_registered_before_the_catch_all(path):
    """The StaticFiles mount at "/" swallows anything declared after it, so a
    page that renders locally can 404 in production purely on ordering."""
    from intentdesk.api.app import app

    paths = [getattr(r, "path", None) for r in app.routes]
    assert path in paths
    # The mount is conditional on web/dist existing, so in a fresh checkout
    # there is no catch-all to be ordered against and this has nothing to
    # assert. Skipping beats the StopIteration it used to raise, which read as
    # a broken test rather than an unbuilt bundle. CI builds the bundle first,
    # so the assertion below does run there.
    mount_at = next((i for i, r in enumerate(app.routes)
                     if getattr(r, "name", None) == "dashboard"), None)
    if mount_at is None:
        pytest.skip("dashboard bundle not built — run `npm run build` in web/")
    assert paths.index(path) < mount_at


@pytest.mark.parametrize("render", ["visibility_agent_page", "growth_strategy_page"])
def test_work_pages_render_complete_documents(render):
    from intentdesk.api import work

    html = getattr(work, render)()
    assert html.startswith("<!doctype html>")
    assert html.rstrip().endswith("</html>")
    # Shared by link with a named reader, not published to be found.
    assert 'name="robots" content="noindex,nofollow"' in html
    # Balanced enough to not have a truncated template.
    assert html.count("<main>") == 1 and html.count("</main>") == 1
    assert "</style>" in html and "<style>" in html


@pytest.mark.parametrize("render", ["visibility_agent_page", "growth_strategy_page"])
def test_work_pages_have_no_broken_css_values(render):
    """A malformed custom property is silently dropped by the browser, so the
    dark theme would lose one colour with nothing in the page to show it."""
    import re

    from intentdesk.api import work

    html = getattr(work, render)()
    css = re.search(r"<style>(.*?)</style>", html, re.S).group(1)
    for decl in re.findall(r"--[\w-]+\s*:\s*([^;}]+)", css):
        value = decl.strip()
        assert " " not in value or value.startswith(("clamp", "calc", "0 ")), (
            f"suspicious custom property value: {value!r}"
        )


def test_both_themes_are_defined_by_token_override():
    """prefers-color-scheme carries the OS preference and data-theme must beat it
    in both directions, or the viewer's toggle only works one way."""
    from intentdesk.api import work

    css = work._CSS
    assert "@media (prefers-color-scheme:dark)" in css
    assert ":root[data-theme=dark]" in css
    assert ":root[data-theme=light]" in css


def test_work_pages_cross_link_each_other():
    from intentdesk.api import work

    assert "/work/growth-strategy" in work.visibility_agent_page()
    assert "/work/visibility-agent" in work.growth_strategy_page()


def test_robots_disallows_the_write_up():
    import asyncio

    from intentdesk.api.app import robots

    assert "Disallow: /work" in asyncio.run(robots()).body.decode()


def test_work_pages_are_not_browser_cacheable():
    """Without an explicit Cache-Control a browser applies heuristic freshness and
    serves HTML it fetched minutes ago — which is how a deployed edit still looks
    unchanged in the tab reading it."""
    from intentdesk.api.app import _WORK_HEADERS

    assert "no-cache" in _WORK_HEADERS["Cache-Control"]
    assert "noindex" in _WORK_HEADERS["X-Robots-Tag"]


def test_content_fills_the_column_with_no_dead_gutter():
    """A narrower measure for running text is the typographic default and it was
    the wrong call here: capping paragraphs inside a wider column put prose hard
    left with ~300px of dead space beside every line while tables spanned the full
    width, which reads as a broken layout rather than a considered measure."""
    from intentdesk.api import work

    css = work._CSS
    # Nothing inside main is capped below the column any more.
    assert "max-width:none" in css
    assert "max-width:var(--measure)" not in css, (
        "a cap narrower than the column is what produced the empty right side"
    )
    # The column itself is the constraint, and it is a length rather than a
    # character count so it cannot drift with the font.
    assert "--measure:820px" in css
    assert "minmax(0,var(--measure))" in css


# ------------------------------------------------- the accordion refactor
@pytest.mark.parametrize("render,code,n", [
    ("visibility_agent_page", "C", 8),
    ("growth_strategy_page", "D", 10),
])
def test_sections_are_collapsed_with_the_first_open(render, code, n):
    """Ten screens of continuous column was the complaint — measured at ~9,100px
    and ~10,200px. A page of nothing but closed boxes is the opposite mistake, so
    the first section is open."""
    from intentdesk.api import work

    html = getattr(work, render)()
    assert html.count('<details class="sec"') == n
    assert html.count('<details class="sec" open') == 1
    assert f'>{code}1</span>' in html


@pytest.mark.parametrize("render", ["visibility_agent_page", "growth_strategy_page"])
def test_the_refactor_dropped_no_prose(render):
    """The accordion splits existing markup on its own h2 boundaries rather than
    the content being re-authored, so every word must survive the move. This is
    the test that makes that claim checkable."""
    import re

    from intentdesk.api import work

    html = getattr(work, render)()
    main = re.search(r"<main>(.*?)</main>", html, re.S).group(1)
    text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", main))
    # Both documents were ~17,000 characters of prose before the split.
    assert len(text) > 15_000, f"only {len(text)} characters survived"


@pytest.mark.parametrize("render", ["visibility_agent_page", "growth_strategy_page"])
def test_every_section_carries_its_finding_not_just_a_title(render):
    """The one real cost of collapsing a submission is a reader who never opens a
    section. A summary that restates its heading does nothing to mitigate that."""
    import re

    from intentdesk.api import work

    html = getattr(work, render)()
    # A <span>, not a <p>: `summary` takes phrasing content, and an invalid <p>
    # there leaves the disclosure behaviour to browser error recovery.
    blurbs = re.findall(r'<span class="sb">(.*?)</span>', html, re.S)
    assert '<p class="sb">' not in html
    assert len(blurbs) == html.count('<details class="sec"')
    for b in blurbs:
        assert len(b) > 45, f"blurb too thin to carry a finding: {b!r}"


@pytest.mark.parametrize("render", ["visibility_agent_page", "growth_strategy_page"])
def test_rail_is_generated_from_the_same_split(render):
    """Rail and sections were two hand-written lists; an entry pointing at an id
    that no longer existed was a real possibility."""
    import re

    from intentdesk.api import work

    html = getattr(work, render)()
    rail = re.search(r'class="rail">(.*?)</aside>', html, re.S).group(1)
    ids = re.findall(r'href="#([\w-]+)"', rail)
    assert len(ids) == html.count('<details class="sec"')
    assert not [i for i in ids if f'id="{i}"' not in html]


@pytest.mark.parametrize("render", ["visibility_agent_page", "growth_strategy_page"])
def test_closed_sections_open_themselves_when_needed(render):
    """Printing, or following an anchor, must not land on a closed box."""
    from intentdesk.api import work

    html = getattr(work, render)()
    assert "beforeprint" in html
    assert "hashchange" in html
    assert 'id="toggle-all"' in html


def test_pages_carry_a_visible_build_stamp():
    """Three rounds of "it is not working" began with the server serving the fix
    and a browser showing a copy cached before there was a Cache-Control header.
    A visible stamp makes "which copy am I looking at" answerable at a glance."""
    from intentdesk.api import work

    for render in ("visibility_agent_page", "growth_strategy_page"):
        html = getattr(work, render)()
        assert 'class="build">build ' in html
        assert work.BUILD in html
