"""What the scheduler is allowed to reach.

The `/cron/*` router is the one surface that runs unattended, so the interesting
property is not that each endpoint works — the service tests cover that — but
which endpoints exist at all. Two ways this goes wrong, both silent:

A paid step gets a cron route, and the bill arrives before anyone notices the
route. `/cron/scan` already refuses this by forcing `free_only` server-side, but
that only defends the one endpoint; a future `/cron/resolve` would bill per row
at 03:15 on a Monday with nothing on screen to say so.

A free step *doesn't* get one, which is how discovery sat behind a browser
session for a day: the organiser pool grew only when somebody clicked, and the
weekly pipeline ran forever over whatever the last click had produced. That
failure has no error and no alert — the queue just stops growing.

So the allow-list below is the specification, and the test fails in both
directions. Adding a route means deciding, in writing, which side it is on.
"""

from intentdesk.api.app import cron

# Free, or billed only in LLM tokens on rows a person already asked for.
SCHEDULABLE = {
    "/discover",  # sitemap fetch — no actor, no credits, no key
    "/scan",      # forces free_only; paid collectors live on /api/collect
    "/classify",  # LLM tokens, over signals already stored
    "/enrich",    # Apollo organizations/* — works on the free plan
    "/draft",     # LLM tokens, capped per run
    "/reconcile", # reads Apify's own spend figure
    "/alerts",
    "/digest",
    "/leads",     # read-only: returns stored rows for the Sheets sync, collects nothing
    "/push-sheet",        # writes stored rows into Google Sheets; the API is free
    "/push-sheet/probe",  # reports whether that push would work
}

# Priced per row or per run. These stay behind an admin session and a button
# with the price on it. Named here so the test says *why* it failed.
NEVER_SCHEDULABLE = {
    "/resolve",       # ~$0.0027 per GMB lookup
    "/collect",       # Trustpilot/G2/Capterra actors, per run
    "/identify",      # Apollo people/match, per row, paid plan only
}


# FastAPI mounts this itself. `docs_url`/`redoc_url` are off but the schema
# route stays, and it is behind the same bearer check as everything else here,
# so it is framework furniture rather than an endpoint anyone scheduled.
FRAMEWORK_ROUTES = {"/openapi.json"}


def _cron_paths():
    return {
        r.path
        for r in cron.routes
        if getattr(r, "path", "").startswith("/") and getattr(r, "methods", None)
    } - FRAMEWORK_ROUTES


def test_every_cron_route_is_free_or_token_billed():
    """A new priced endpoint must not be reachable without a person present."""
    unexpected = _cron_paths() - SCHEDULABLE
    assert not unexpected, (
        f"{sorted(unexpected)} is on the cron router and not in the allow-list. "
        "If it bills per row or per run it belongs on /api/* behind an admin "
        "session; if it is free, add it to SCHEDULABLE and to the n8n workflow."
    )


def test_paid_actions_never_reach_the_cron_router():
    assert not (_cron_paths() & NEVER_SCHEDULABLE)


def test_free_discovery_is_actually_scheduled():
    """The regression this file was written for.

    Discovery is free, so leaving it off the schedule cost nothing and looked
    like nothing — the organiser count simply stopped moving between clicks.
    """
    assert "/discover" in _cron_paths()


def test_every_schedulable_route_exists():
    """Catches the allow-list drifting ahead of the code: a name listed here but
    never implemented reads as covered when it is not."""
    missing = SCHEDULABLE - _cron_paths()
    assert not missing, f"{sorted(missing)} is allow-listed but not implemented"
