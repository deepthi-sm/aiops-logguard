"""
asyncpg connection pool — lifespan-managed, FastAPI-dependency exposed.

The pool is created at app startup (`api.main` lifespan) when
`LOGGUARD_DB_URL` is set, and stored on `app.state.pool`. Routes that
need DB access take it via `Depends(get_pool)`. Two practical reasons
the pool lives on `app.state` rather than as a module global:

  * It cooperates with `TestClient`, which constructs a fresh app
    instance per test session.
  * It plays nicely with FastAPI's dependency_overrides — tests can
    inject a different pool without monkey-patching globals.

Routes that depend on `get_pool` will 503 cleanly when the pool isn't
available (e.g. the operator forgot to set the env var, or Postgres is
down at boot). Don't return mock data in that situation — surface the
config error explicitly.
"""
from __future__ import annotations

import asyncpg
from fastapi import HTTPException, Request, status

DB_URL_ENV = "LOGGUARD_DB_URL"

DEFAULT_POOL_MIN_SIZE = 1
DEFAULT_POOL_MAX_SIZE = 10
DEFAULT_POOL_TIMEOUT_S = 30.0


async def create_pool(url: str) -> asyncpg.Pool:
    """Build a fresh asyncpg pool. Used by the FastAPI lifespan and tests."""
    return await asyncpg.create_pool(
        url,
        min_size=DEFAULT_POOL_MIN_SIZE,
        max_size=DEFAULT_POOL_MAX_SIZE,
        timeout=DEFAULT_POOL_TIMEOUT_S,
    )


async def close_pool(pool: asyncpg.Pool | None) -> None:
    """Idempotent close — accepts None for the lifespan-shutdown path
    where the pool may never have been created."""
    if pool is not None:
        await pool.close()


async def get_pool(request: Request) -> asyncpg.Pool:
    """FastAPI dependency. Returns the active pool or 503 if unavailable.

    Tests that need to inject a different pool override this dependency
    via `app.dependency_overrides[get_pool] = lambda: test_pool`.
    """
    pool = getattr(request.app.state, "pool", None)
    if pool is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                f"Database not connected. Set the {DB_URL_ENV} env var "
                "to a postgresql:// URL and ensure Postgres is reachable."
            ),
        )
    return pool
