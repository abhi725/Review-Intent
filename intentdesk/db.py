"""asyncpg pool. Kept deliberately thin — no ORM, this VM is short on RAM."""

import json
from typing import Any, Optional

import asyncpg

from intentdesk.config import settings

_pool: Optional[asyncpg.Pool] = None


async def _init_conn(conn: asyncpg.Connection) -> None:
    # Without this asyncpg hands back JSON columns as raw strings.
    for typename in ("json", "jsonb"):
        await conn.set_type_codec(
            typename, encoder=json.dumps, decoder=json.loads, schema="pg_catalog"
        )


async def connect() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(
            dsn=settings.database_url,
            min_size=1,
            max_size=8,
            command_timeout=30,
            init=_init_conn,
        )
    return _pool


async def disconnect() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


def pool() -> asyncpg.Pool:
    if _pool is None:
        raise RuntimeError("db.connect() has not run yet")
    return _pool


async def fetch(sql: str, *args: Any) -> list[dict]:
    rows = await pool().fetch(sql, *args)
    return [dict(r) for r in rows]


async def fetchrow(sql: str, *args: Any) -> Optional[dict]:
    row = await pool().fetchrow(sql, *args)
    return dict(row) if row else None


async def fetchval(sql: str, *args: Any) -> Any:
    return await pool().fetchval(sql, *args)


async def execute(sql: str, *args: Any) -> str:
    return await pool().execute(sql, *args)
