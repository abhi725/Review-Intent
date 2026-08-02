"""Runtime settings, backed by the `settings` table.

Environment variables give the defaults; anything saved here overrides them, so
the team can retune targeting from the dashboard without a redeploy.
"""

from typing import Any

from intentdesk import db, market
from intentdesk.config import settings as env

DEFAULTS: dict[str, Any] = {
    "target_country": env.target_country,
    "target_agents_min": env.target_agents_min,
    "target_agents_max": env.target_agents_max,
    "signal_recency_days": env.signal_recency_days,
    "monthly_spend_cap_usd": env.monthly_spend_cap_usd,
    "value_proposition": market.DEFAULT_VALUE_PROPOSITION,
    # Which channel the desk is working. Apollo's free plan returns company
    # phone numbers but no email addresses, so "phone" is the only setting that
    # produces contactable leads without a paid plan.
    "outreach_channel": "phone",
    # Who may sign in. Runtime rather than env, so tightening access does not
    # need a redeploy — and it is checked on every sign-in, not just at
    # registration, so tightening it locks out accounts created while it was
    # loose.
    #   open      — any Google account, and any address may register
    #   domain    — only addresses on allowed_email_domains
    #   allowlist — those domains, plus addresses that already have an account
    "access_mode": env.access_mode,
    "allowed_email_domains": env.allowed_email_domain,
}

EDITABLE = set(DEFAULTS)

CHANNELS = ("phone", "email", "both")
ACCESS_MODES = ("open", "domain", "allowlist")


async def all_prefs() -> dict:
    rows = await db.fetch("SELECT key, value FROM settings")
    stored = {r["key"]: r["value"] for r in rows}
    return {k: stored.get(k, default) for k, default in DEFAULTS.items()}


async def get(key: str) -> Any:
    row = await db.fetchrow("SELECT value FROM settings WHERE key = $1", key)
    return row["value"] if row else DEFAULTS.get(key)


async def update(changes: dict) -> dict:
    """Persist a partial update. Unknown keys are rejected rather than stored,
    so a typo cannot silently become a setting nothing reads."""
    unknown = set(changes) - EDITABLE
    if unknown:
        raise ValueError(f"unknown setting(s): {', '.join(sorted(unknown))}")

    channel = changes.get("outreach_channel")
    if channel is not None and channel not in CHANNELS:
        raise ValueError(f"outreach_channel must be one of {CHANNELS}, got {channel!r}")

    mode = changes.get("access_mode")
    if mode is not None and mode not in ACCESS_MODES:
        raise ValueError(f"access_mode must be one of {ACCESS_MODES}, got {mode!r}")

    # A domain rule with no domains locks everyone out including the person
    # setting it, and the only way back is a psql session.
    if mode in ("domain", "allowlist"):
        domains = changes.get("allowed_email_domains", (await get("allowed_email_domains")))
        if not str(domains or "").strip():
            raise ValueError(
                f"access_mode {mode!r} needs at least one entry in allowed_email_domains"
            )

    for key, value in changes.items():
        await db.execute(
            """
            INSERT INTO settings (key, value) VALUES ($1, $2::jsonb)
            ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now()
            """,
            key,
            value,
        )
    return await all_prefs()


async def agent_band() -> tuple[int, int]:
    prefs = await all_prefs()
    return int(prefs["target_agents_min"]), int(prefs["target_agents_max"])


async def value_proposition_is_default() -> bool:
    """True while nobody has replaced the placeholder pitch.

    Every draft inherits this string, and a generic pitch is the difference
    between outreach worth sending and one that reads like every other vendor.
    Surfaced in stats so the gap is visible rather than assumed to be filled.
    Checks the whole placeholder set, not just the current default — a pitch
    typed once to clear the field is still an unanswered question."""
    return (await get("value_proposition")) in market.PLACEHOLDER_VALUE_PROPOSITIONS


async def channel() -> str:
    return str((await all_prefs())["outreach_channel"])
