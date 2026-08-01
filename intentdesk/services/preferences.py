"""Runtime settings, backed by the `settings` table.

Environment variables give the defaults; anything saved here overrides them, so
the team can retune targeting from the dashboard without a redeploy.
"""

from typing import Any

from intentdesk import db
from intentdesk.config import settings as env

DEFAULTS: dict[str, Any] = {
    "target_country": env.target_country,
    "target_agents_min": env.target_agents_min,
    "target_agents_max": env.target_agents_max,
    "signal_recency_days": env.signal_recency_days,
    "monthly_spend_cap_usd": env.monthly_spend_cap_usd,
    "value_proposition": "AI voice and WhatsApp on the front line, so routine tickets never reach an agent",
}

EDITABLE = set(DEFAULTS)


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
