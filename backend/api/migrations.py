"""
Schema migrations — apply `backend/api/schema.sql` on startup.

The schema file is a verbatim copy of `docs/architecture/database_schema.sql`
(the source-of-truth doc) — they're pinned byte-identical by
`tests/test_schema_sync.py` so they can't drift. The doc is the design
record; this is the deployable copy that ships in the Docker image.

Every statement is idempotent (`CREATE TABLE IF NOT EXISTS`,
`CREATE INDEX IF NOT EXISTS`) so this is safe to re-run on every boot.
"""
from __future__ import annotations

from pathlib import Path

import asyncpg

SCHEMA_PATH = Path(__file__).parent / "schema.sql"


def load_schema_sql() -> str:
    return SCHEMA_PATH.read_text(encoding="utf-8")


async def apply_schema(pool: asyncpg.Pool) -> None:
    """Run every statement in schema.sql against the pool. Idempotent."""
    sql = load_schema_sql()
    async with pool.acquire() as conn:
        await conn.execute(sql)
