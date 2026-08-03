"""Every secret that is configured must actually reach the container.

`docker-compose.prod.yml` lists environment variables explicitly, so it is an
allow-list, and a setting added to `config.py` and `.env.prod` but not to that
list is simply absent in production. The failure is silent in the worst way,
because the code paths that consume these values are written to tolerate their
absence: a missing `APOLLO_API_KEY` makes `organizations/enrich` and the domain
resolver report *no result*, which is indistinguishable from a company Apollo
genuinely does not know. Nothing raises, nothing alerts, and the queue just
looks like a queue of hard-to-resolve companies.

This has now happened twice. On 2026-08-02 it was `PUBLIC_BASE_URL`, caught
before deploy, where the fallback would have emailed real people verification
links pointing at localhost. On 2026-08-03 it was `APOLLO_API_KEY`, caught only
because `/cron/enrich` happens to name the missing key in its response — after a
day of resolution attempts in prod that could never have succeeded.

So this test compares the three files instead of trusting a checklist. It reads
`.env.prod` when present, which is the developer/VM case, and skips that half
where the file is absent, which is the CI case — the comparison of `config.py`
against compose still runs there.
"""

import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
COMPOSE = ROOT / "docker-compose.prod.yml"
ENV_PROD = ROOT / ".env.prod"
ENV_EXAMPLE = ROOT / ".env.example"

# Local-only, or deliberately left at the code default in prod. Anything not
# listed here has to be passed through — the point is that the exception is
# written down rather than assumed.
NOT_IN_PROD = {
    "API_PORT",           # set by the image's CMD
    "MCP_HTTP_PORT",      # the MCP app is mounted, not run on its own port
    "BUILTWITH_API_KEY",  # $295/mo, never bought; organizations/enrich replaced it
    "REDDIT_USER_AGENT",  # code default is correct and not a secret
    # Targeting/scoring knobs: the code defaults are the intended production
    # values, and passing them as empty strings would override those defaults
    # with nothing — the exact bug this file exists to catch, inverted.
    "SIGNAL_RECENCY_DAYS",
    "TARGET_AGENTS_MAX",
    "TARGET_AGENTS_MIN",
    "TARGET_COUNTRY",
}


def _compose_keys() -> set[str]:
    return set(re.findall(r"^\s+([A-Z][A-Z0-9_]*):", COMPOSE.read_text(), re.M))


def _env_keys(path: pathlib.Path) -> set[str]:
    return set(re.findall(r"^([A-Z][A-Z0-9_]*)=", path.read_text(), re.M))


def _config_settings() -> set[str]:
    text = (ROOT / "intentdesk" / "config.py").read_text()
    return {n.upper() for n in re.findall(r"^\s{4}([a-z][a-z0-9_]*)\s*:", text, re.M)}


def test_every_configured_value_is_passed_through():
    """The one that would have caught APOLLO_API_KEY on the day it was added."""
    if not ENV_PROD.exists():
        pytest.skip(".env.prod is not present (CI)")
    missing = _env_keys(ENV_PROD) - _compose_keys()
    assert not missing, (
        f"{sorted(missing)} is set in .env.prod but not listed in the compose "
        "environment block, so the container will never see it. Nothing will "
        "error — the features that use it will report finding nothing."
    )


def test_config_settings_are_either_passed_through_or_excused():
    settings = _config_settings()
    unaccounted = settings - _compose_keys() - NOT_IN_PROD
    assert not unaccounted, (
        f"{sorted(unaccounted)} exists in config.py but is neither passed "
        "through compose nor listed in NOT_IN_PROD. Decide which, in writing."
    )


def test_exclusions_still_exist_in_config():
    """Stops NOT_IN_PROD rotting into a list of names nothing uses, which would
    quietly excuse a real setting that later takes one of these names."""
    stale = NOT_IN_PROD - _config_settings()
    assert not stale, f"{sorted(stale)} is excused but no longer a setting"


def test_example_env_documents_the_keys_prod_needs():
    """`.env.example` is what the next deploy is built from. A key that prod
    requires and the example omits is a deploy that starts and misbehaves."""
    if not ENV_EXAMPLE.exists():
        pytest.skip("no .env.example")
    secrets = {k for k in _compose_keys() if k.endswith(("_KEY", "_SECRET", "_TOKEN"))}
    undocumented = secrets - _env_keys(ENV_EXAMPLE)
    assert not undocumented, f"{sorted(undocumented)} is not in .env.example"
