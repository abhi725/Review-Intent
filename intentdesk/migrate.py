"""Apply SQL migrations in order.

Runs at container start so a deploy against an empty database provisions itself
instead of coming up with no tables. Safe to run repeatedly: each file is
recorded in `schema_migrations` and skipped once applied.

    python -m intentdesk.migrate
"""

import asyncio
import sys
from pathlib import Path

import asyncpg

from intentdesk.config import ROOT, settings

MIGRATIONS = ROOT / "migrations"

BOOTSTRAP = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version    TEXT PRIMARY KEY,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
)
"""


def _pending(applied: set[str]) -> list[Path]:
    files = sorted(MIGRATIONS.glob("*.sql"), key=lambda p: p.name)
    return [f for f in files if f.stem not in applied]


async def migrate() -> int:
    conn = await asyncpg.connect(settings.database_url)
    try:
        await conn.execute(BOOTSTRAP)
        applied = {r["version"] for r in await conn.fetch("SELECT version FROM schema_migrations")}

        pending = _pending(applied)
        if not pending:
            print(f"migrations: up to date ({len(applied)} applied)")
            return 0

        for path in pending:
            print(f"migrations: applying {path.name}")
            sql = path.read_text()
            # One transaction per file: a failure leaves the database on the
            # last good migration rather than half-way through a broken one.
            async with conn.transaction():
                await conn.execute(sql)
                await conn.execute(
                    "INSERT INTO schema_migrations (version) VALUES ($1) "
                    "ON CONFLICT (version) DO NOTHING",
                    path.stem,
                )
        print(f"migrations: applied {len(pending)}")
        return len(pending)
    finally:
        await conn.close()


async def wait_for_db(timeout_s: int = 60) -> None:
    """Postgres may still be starting when the app container does."""
    waited = 0
    while True:
        try:
            conn = await asyncpg.connect(settings.database_url)
            await conn.close()
            return
        except (OSError, asyncpg.PostgresError) as exc:
            if waited >= timeout_s:
                raise RuntimeError(f"database unreachable after {timeout_s}s: {exc}")
            await asyncio.sleep(2)
            waited += 2


async def main() -> None:
    await wait_for_db()
    await migrate()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as exc:
        print(f"migrations failed: {exc}", file=sys.stderr)
        sys.exit(1)
