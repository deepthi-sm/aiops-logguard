"""
Tests for `api.db` and `api.migrations` and the lifespan integration.

The `seeded_db` and `client` fixtures live in `tests/conftest.py`. Tests
that exercise the pool / schema directly use their own short-lived pool
via `asyncio.run`-friendly async test functions — easier than coordinating
loops with TestClient.

Skipped on machines without `LOGGUARD_DB_URL` set — see conftest.
"""
from __future__ import annotations

import os

import asyncpg
import pytest
from fastapi.testclient import TestClient

from api.db import DB_URL_ENV, close_pool, create_pool, get_pool
from api.main import app
from api.migrations import apply_schema
from api.repository import install_jsonb_codec


def _require_db_url() -> str:
    url = os.environ.get(DB_URL_ENV)
    if not url:
        pytest.skip(
            f"{DB_URL_ENV} not set — set it to a postgresql:// URL or run "
            "`docker compose up -d postgres`."
        )
    return url


# -- direct pool / schema tests --------------------------------------------


async def test_pool_round_trips_a_simple_query():
    url = _require_db_url()
    pool = await create_pool(url)
    try:
        async with pool.acquire() as conn:
            assert await conn.fetchval("SELECT 1") == 1
    finally:
        await pool.close()


async def test_apply_schema_is_idempotent():
    """Every statement is `CREATE … IF NOT EXISTS` — running twice
    must not error (boot-on-fresh-DB and boot-on-existing-DB take the
    same code path)."""
    url = _require_db_url()
    pool = await create_pool(url)
    try:
        async with pool.acquire() as conn:
            await install_jsonb_codec(conn)
        await apply_schema(pool)
        await apply_schema(pool)
    finally:
        await pool.close()


async def test_apply_schema_creates_required_tables():
    """Sanity check that the schema in backend/api/schema.sql produces
    the tables the rest of the system queries."""
    url = _require_db_url()
    pool = await create_pool(url)
    try:
        await apply_schema(pool)
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
            )
        present = {r["tablename"] for r in rows}
    finally:
        await pool.close()
    expected = {"anomalies", "drift_events", "training_runs"}
    missing = expected - present
    assert not missing, f"schema is missing: {missing}"


async def test_close_pool_accepts_none():
    """Lifespan-shutdown calls this before lifespan-startup may have
    initialised the pool, so it must be tolerant of None."""
    await close_pool(None)


# -- 503 path when no pool ---------------------------------------------------


def test_db_dependent_route_returns_503_when_pool_missing(monkeypatch):
    """When `LOGGUARD_DB_URL` is unset DB-dependent routes must 503
    cleanly rather than crashing. Construct TestClient WITHOUT entering
    its context so lifespan doesn't run; routes then see no pool."""
    monkeypatch.delenv(DB_URL_ENV, raising=False)
    saved_pool = getattr(app.state, "pool", None)
    saved_override = app.dependency_overrides.pop(get_pool, None)
    app.state.pool = None
    try:
        client = TestClient(app)  # NB: no `with` → no lifespan
        r = client.get("/api/v1/anomalies")
        assert r.status_code == 503
        assert "Database not connected" in r.json()["detail"]
    finally:
        app.state.pool = saved_pool
        if saved_override is not None:
            app.dependency_overrides[get_pool] = saved_override


def test_health_endpoint_works_without_pool(monkeypatch):
    """The /health endpoint deliberately doesn't depend on the DB so
    Kubernetes liveness probes work even during a Postgres outage."""
    monkeypatch.delenv(DB_URL_ENV, raising=False)
    saved_pool = getattr(app.state, "pool", None)
    saved_override = app.dependency_overrides.pop(get_pool, None)
    app.state.pool = None
    try:
        client = TestClient(app)
        r = client.get("/api/v1/health")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"
    finally:
        app.state.pool = saved_pool
        if saved_override is not None:
            app.dependency_overrides[get_pool] = saved_override


# -- the `client` fixture really has rows --------------------------------


def test_client_fixture_has_seeded_rows(client: TestClient):
    """Smoke check: the conftest's seeded_db fixture really did INSERT
    the canonical anomalies, and the lifespan-managed pool sees them."""
    r = client.get("/api/v1/anomalies")
    assert r.status_code == 200
    assert len(r.json()["items"]) > 0


@pytest.mark.parametrize("severity", ["critical", "warning", "info"])
def test_client_fixture_covers_every_severity(client: TestClient, severity: str):
    """Pin that the seed data covers every severity branch — otherwise
    the route tests' severity-filter assertions would silently never
    exercise."""
    r = client.get(f"/api/v1/anomalies?severity={severity}")
    assert r.status_code == 200
    assert len(r.json()["items"]) >= 1


# Suppress unused-import warning — asyncpg is referenced via type hints elsewhere
_ = asyncpg
