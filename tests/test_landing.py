"""The public landing page.

Two classes of thing are worth testing on a marketing page, and neither is the
copy: that it is actually reachable without a session, and that it does not
claim capabilities the product does not have. The second one is why
`market.py` is imported here — the page and the truth are checked against each
other rather than against my memory of them.
"""

import re

import pytest

from intentdesk.api import landing, pages
from intentdesk import market


@pytest.fixture(scope="module")
def html():
    return landing.landing_page()


# --------------------------------------------------------------- reachability


def test_page_is_indexable(html):
    """`pages._shell` emits noindex, which is right for a login screen and the
    single tag most able to quietly make this page pointless."""
    assert "noindex" not in html
    assert "nofollow" not in html


def test_shell_is_not_the_auth_shell(html):
    """Guards against someone 'simplifying' this to reuse pages._shell."""
    assert 'rel="canonical"' in html or "rel='canonical'" in html
    assert "og:title" in html and "application/ld+json" in html


def test_landing_route_needs_no_session():
    """The one regression that would make the whole page useless."""
    from intentdesk.api.app import app

    route = next(r for r in app.routes if getattr(r, "path", None) == "/")
    assert "GET" in route.methods
    # No dependency may resolve to the session gate.
    assert not getattr(route, "dependant", None) or all(
        d.call.__name__ != "require_user"
        for d in route.dependant.dependencies
    )


def test_app_shell_route_exists():
    """The dashboard has to still be reachable after / was taken from it."""
    from intentdesk.api.app import app

    assert any(getattr(r, "path", None) == "/app" for r in app.routes)


def test_signin_lands_on_the_app_not_the_landing_page():
    """Redirecting to "/" after sign-in would drop the user back on marketing
    copy, which reads as the sign-in having failed."""
    import inspect

    from intentdesk.api import app as app_module

    for fn in (app_module.auth_password, app_module.auth_callback):
        src = inspect.getsource(fn)
        assert 'RedirectResponse("/", status_code=303)' not in src
        assert '"/app"' in src


# ------------------------------------------------------------------ the form


def test_signup_form_posts_to_a_real_route(html):
    """A form action that 404s is invisible until someone tries to sign up."""
    from intentdesk.api.app import app

    action = re.search(r"<form[^>]+action='([^']+)'", html).group(1)
    assert action == "/auth/register"

    route = next(r for r in app.routes if getattr(r, "path", None) == action)
    assert "POST" in route.methods


def test_form_enforces_the_same_password_floor_as_the_service(html):
    """A client minlength below the server's would produce a rejection the
    visitor could not have predicted."""
    from intentdesk.services.users import MIN_PASSWORD_LENGTH

    assert f"minlength='{MIN_PASSWORD_LENGTH}'" in html


def test_every_nav_anchor_has_a_section(html):
    """A nav that scrolls nowhere is the easiest thing on a landing page to
    ship broken, because it still looks fine."""
    anchors = set(re.findall(r"href='#([a-z-]+)'", html))
    ids = set(re.findall(r"id='([a-z-]+)'", html))
    assert anchors, "no in-page anchors found at all"
    assert anchors <= ids, f"anchors with no target: {anchors - ids}"


def test_offers_both_signup_and_signin_paths(html):
    assert "/login" in html
    assert "/auth/login" in html  # the Google button


# ------------------------------------------------------------- honest claims


def test_does_not_claim_the_broken_collectors_work(html):
    """market.py records these as tried-and-failed. Describing them as working
    is the false-claims problem the Swan Digitals site audit flagged."""
    assert market.REVIEW_SOURCES["capterra"]["status"] == "blocked"
    assert "Capterra" not in html

    # Job postings may appear, but only carrying their real status.
    if "Job postings" in html:
        row = html.split("Job postings", 1)[1][:400]
        assert "not usable" in row, "job postings listed without its real status"


def test_watchlist_shown_matches_the_configured_market(html):
    """The page renders competitors from market.ACTIVE_COMPETITORS, so it cannot
    drift into advertising a platform the product does not watch."""
    for name in market.ACTIVE_COMPETITORS:
        assert name in html


def test_registered_but_inactive_brands_are_not_advertised(html):
    """Phase C registered an expansion set that is deliberately switched off.
    Listing those here would claim coverage the scan does not have — the page
    would name Humanitix while no collector ever looks at it."""
    inactive = [n for n, b in market.BRANDS.items() if not b.get("active")]
    assert inactive, "the fixture is meaningless if every brand is active"
    for name in inactive:
        assert name not in html, f"{name} is not scanned but appears on the page"


def test_no_invented_pricing(html):
    """There is no pricing yet, and a number on a web page becomes a promise."""
    assert not re.search(r"[₹$]\s?\d", html), "a price appeared on the page"


def test_no_testimonials_or_client_logos(html):
    """Excluded by request, and there are none to show."""
    lowered = html.lower()
    for banned in ("testimonial", "trusted by", "our clients", "case study"):
        assert banned not in lowered


def test_states_that_nothing_sends_itself(html):
    """The strongest true differentiator; losing it in an edit would be a
    silent downgrade."""
    assert "never contacts anyone" in html


def test_palette_is_shared_with_the_auth_pages(html):
    """One brand, one source. Drift here shows up as a landing page and a login
    page that look like different products."""
    assert pages.BRAND["orange"] in html
