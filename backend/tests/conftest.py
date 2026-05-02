"""
Shared pytest fixtures.

The DB-backed route tests need a real Postgres connection. CI provides
one via the postgres service in `.github/workflows/ci.yml`; locally
you can run `docker compose up -d postgres`. When `LOGGUARD_DB_URL`
isn't set we skip with a clear message — better than silently passing
tests that should be exercising the SQL path.

Pool / loop strategy

  asyncpg pools are bound to the event loop they're created in. The
  obvious "session-scoped pool" pattern collides with both pytest-
  asyncio (function-scoped event loop by default) and TestClient
  (which spins up its own portal-managed loop for the lifespan).

  The pragmatic answer: don't share a pool across the seed code and
  the request code. The `seeded_db` fixture runs setup + teardown
  through short-lived `asyncio.run(...)` connections that close before
  TestClient even starts. TestClient's lifespan then creates its OWN
  pool from the same `LOGGUARD_DB_URL` and uses that for all in-test
  queries. Both pools talk to the same database, so the seed data is
  visible to the request handlers.
"""
from __future__ import annotations

import os

# Defuse the OpenMP DLL conflict between PyTorch (libiomp5md.dll) and
# FAISS (libomp140.x86_64.dll) on Windows when both are imported in the
# same process. Without this, any test that imports faiss AFTER torch
# (or vice versa) hangs or aborts mid-test. CI on Linux doesn't hit
# this; setting it unconditionally is harmless on Linux/macOS too.
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")

import asyncio  # noqa: E402
from collections.abc import Iterator  # noqa: E402
from datetime import UTC, datetime, timedelta  # noqa: E402

import asyncpg  # noqa: E402
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from api import mock_data  # noqa: E402
from api.db import DB_URL_ENV, create_pool  # noqa: E402
from api.main import app  # noqa: E402
from api.migrations import apply_schema  # noqa: E402
from api.repository import install_jsonb_codec  # noqa: E402
from api.schemas import Anomaly  # noqa: E402


def _db_url() -> str | None:
    return os.environ.get(DB_URL_ENV)


# -- DB setup helpers (each opens + closes its own connection) --------------


async def _truncate(pool: asyncpg.Pool) -> None:
    async with pool.acquire() as conn:
        await conn.execute(
            "TRUNCATE TABLE anomalies, drift_events, training_runs RESTART IDENTITY"
        )


async def _seed_anomalies(pool: asyncpg.Pool) -> None:
    """Insert the canonical mock fixtures so the existing route tests
    keep their assertions. Also fills `root_cause` / `recommended_fix`
    / `similar_incidents` for anomalies that have a corresponding mock
    explanation, so /explanation returns the same content."""
    async with pool.acquire() as conn:
        for a in mock_data.all_anomalies():
            await _insert_anomaly_with_explanation(conn, a)


async def _insert_anomaly_with_explanation(
    conn: asyncpg.Connection, a: Anomaly
) -> None:
    explanation = mock_data.explanation_for(a.id)
    root_cause = explanation.root_cause if explanation else None
    recommended_fix = explanation.recommended_fix if explanation else None
    similar_json = (
        [s.model_dump(mode="json") for s in explanation.similar_incidents]
        if explanation
        else None
    )
    await conn.execute(
        """
        INSERT INTO anomalies (
            id, detected_at, severity, source,
            ensemble_score, confidence, failure_probability,
            predicted_failure_window_min,
            log_template, sequence_preview, top_contributing_lines,
            explanation_status, cluster_id, cluster_size,
            root_cause, recommended_fix, similar_incidents
        ) VALUES (
            $1, $2, $3, $4,
            $5, $6, $7,
            $8,
            $9, $10, $11,
            $12, $13, $14,
            $15, $16, $17
        )
        """,
        a.id,
        a.detected_at,
        a.severity,
        a.source,
        a.ensemble_score,
        a.confidence,
        a.failure_probability,
        a.predicted_failure_window_min,
        a.log_template,
        list(a.sequence_preview),
        [c.model_dump(mode="json") for c in a.top_contributing_lines],
        a.explanation_status,
        a.cluster_id,
        a.cluster_size,
        root_cause,
        recommended_fix,
        similar_json,
    )


async def _seed_training_run(pool: asyncpg.Pool) -> None:
    """Seed `training_runs` so /metrics/summary's `last_retrain` and
    /system/drift's `last_retrain` return the same value `mock_data` used."""
    summary = mock_data.metrics_summary()
    if summary.last_retrain is None:
        return
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO training_runs (started_at, completed_at, dataset, f1_score)
            VALUES ($1, $2, 'mock-fixture', 0.92)
            """,
            summary.last_retrain - timedelta(hours=2),
            summary.last_retrain,
        )


async def _seed_drift_event(pool: asyncpg.Pool) -> None:
    """Insert a drift event when the mock fixture's status would have
    produced one. The schema CHECK constraint accepts only
    'drift_high' / 'drift_critical' — for the 'healthy' fixture we
    intentionally seed nothing so the repository's default-when-empty
    path produces the matching healthy DriftStatus."""
    drift = mock_data.drift_status()
    if drift.status == "healthy":
        return
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO drift_events (detected_at, psi_score, severity)
            VALUES ($1, $2, $3)
            """,
            datetime.now(UTC),
            drift.psi_score,
            drift.status,
        )


async def _setup_db(url: str) -> None:
    """Open a one-shot pool, apply schema, truncate, seed, close."""
    pool = await create_pool(url)
    try:
        async with pool.acquire() as conn:
            await install_jsonb_codec(conn)
        await apply_schema(pool)
        await _truncate(pool)
        await _seed_anomalies(pool)
        await _seed_training_run(pool)
        await _seed_drift_event(pool)
    finally:
        await pool.close()


async def _teardown_db(url: str) -> None:
    """Truncate so the next test starts clean. Open a fresh pool because
    setup's pool was closed."""
    pool = await create_pool(url)
    try:
        async with pool.acquire() as conn:
            await install_jsonb_codec(conn)
        await _truncate(pool)
    finally:
        await pool.close()


# -- public fixtures --------------------------------------------------------


@pytest.fixture
def seeded_db() -> Iterator[None]:
    """Sync fixture: seed mock fixtures via short-lived asyncio.run()
    connections, yield, then truncate. The DB-backed pool that
    request handlers use is lifespan-created INSIDE TestClient — see
    the `client` fixture."""
    url = _db_url()
    if not url:
        pytest.skip(
            f"{DB_URL_ENV} not set — DB-backed route tests require Postgres "
            "(see .github/workflows/ci.yml or `docker compose up -d postgres`)."
        )
    try:
        asyncio.run(_setup_db(url))
    except (OSError, asyncpg.PostgresError) as e:
        pytest.skip(f"Postgres unreachable at {DB_URL_ENV}={url!r}: {e}")
    try:
        yield
    finally:
        # Don't suppress test errors with a teardown failure — log instead.
        try:
            asyncio.run(_teardown_db(url))
        except Exception:  # noqa: BLE001
            pass


@pytest.fixture
def client(seeded_db) -> Iterator[TestClient]:
    """TestClient. Lifespan reads `LOGGUARD_DB_URL` from env, creates a
    pool, applies the schema (idempotent), and stores it on
    `app.state.pool`. The seed fixture has already populated the rows
    using a one-shot connection that closed before TestClient started,
    so the lifespan's pool sees those rows."""
    _ = seeded_db  # ensure ordering
    with TestClient(app) as c:
        yield c


__all__ = ["seeded_db", "client"]
