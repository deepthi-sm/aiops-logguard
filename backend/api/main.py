"""
FastAPI application entrypoint.

Lifespan responsibilities (Step 4b-ii onwards):
  * Build the asyncpg pool when `LOGGUARD_DB_URL` is set.
  * Apply `api/schema.sql` to the database (idempotent — every statement
    is `CREATE … IF NOT EXISTS`, safe to re-run on every boot).
  * Install the JSONB codec on each connection so reads/writes deserialise
    list/dict columns automatically.
  * Stash the pool on `app.state.pool`. Routes pull it via the
    `api.db.get_pool` dependency and 503 if it's missing.

If the env var is unset at boot the app still starts (so devs can hit
`/api/v1/health` without a Postgres on their machine), but every
DB-dependent route returns 503. CI sets the env var and seeds the
schema, so the existing route tests continue to assert against real
data — the test conftest provides a per-test seed/truncate fixture.
"""
import logging
import os
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.db import DB_URL_ENV, close_pool, create_pool
from api.migrations import apply_schema
from api.repository import install_jsonb_codec
from api.routes import router as rest_router
from api.schemas import HealthResponse
from api.ws import router as ws_router

VERSION = os.environ.get("LOGGUARD_VERSION", "0.1.0")
_started_at = time.monotonic()
_log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    db_url = os.environ.get(DB_URL_ENV)
    pool = None
    if db_url:
        pool = await create_pool(db_url)
        async with pool.acquire() as conn:
            await install_jsonb_codec(conn)
        await apply_schema(pool)
        _log.info("postgres pool initialised + schema applied")
    else:
        _log.warning(
            "%s not set — DB-dependent routes will return 503 until configured",
            DB_URL_ENV,
        )
    app.state.pool = pool
    try:
        yield
    finally:
        await close_pool(pool)
        app.state.pool = None


app = FastAPI(
    title="AIOps-LogGuard API",
    version=VERSION,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(rest_router)
app.include_router(ws_router)


@app.get("/api/v1/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(
        status="ok",
        version=VERSION,
        uptime_s=int(time.monotonic() - _started_at),
    )
