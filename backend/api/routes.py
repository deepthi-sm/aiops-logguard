"""
REST endpoints — the integration contract with the frontend
(docs/architecture/api_contract.md).

Step 4b-ii: handlers now query Postgres via `api.repository`. The schema
contract (Pydantic models, status codes, pagination cursor) is unchanged
from Step 2 — only the data source is different. Tests seed the DB with
the same fixtures Step 2 served from `mock_data`, so existing assertions
still hold.
"""
import asyncio
import base64
import binascii
import json
import logging
import os
import time
from datetime import UTC, datetime
from typing import Annotated

import asyncpg
import redis.asyncio as redis_aio
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from api import repository
from api.db import get_pool
from api.schemas import (
    Anomaly,
    AnomalyListResponse,
    DriftStatus,
    Explanation,
    FeedbackHistoryItem,
    FeedbackHistoryResponse,
    FeedbackRequest,
    FeedbackResponse,
    MetricsSummary,
    Severity,
    SystemQueueResponse,
    SystemService,
    SystemServicesResponse,
    TimelineResponse,
    TimelineWindow,
    TrainingRunsResponse,
)

_log = logging.getLogger(__name__)

# Redis SET the RAG explainer pops from before its DB poll. When a
# user GETs /explanation on a pending anomaly we SADD the id here so
# the worker explains it next, instead of leaving the user waiting
# behind hundreds of un-viewed anomalies in the upload backlog.
#
# SET (not LIST) — the frontend polls /explanation every 2s while
# pending, which previously LPUSHed dozens of duplicate ids per click.
# That starved OTHER clicked anomalies because the worker spent its
# rounds popping dups. SADD is idempotent: one click = one entry
# regardless of poll count.
#
# New key name (`...:set`) to avoid a Redis WRONGTYPE collision with
# the legacy LIST at the same name in environments that haven't been
# wiped. Migration: the legacy LIST is now dead code; safe to ignore.
PRIORITY_SET = "anomalies:priority:set"


async def _bump_explanation_priority(anomaly_id: str) -> None:
    """Best-effort priority bump. Failures (Redis down, network blip)
    must NOT fail the GET — the explanation will eventually surface
    via the worker's normal LIFO DB poll, just slower."""
    try:
        url = os.environ.get("LOGGUARD_REDIS_URL", "redis://localhost:6379")
        client = redis_aio.from_url(url, decode_responses=True)
        try:
            # SADD is idempotent — repeated polls of the same anomaly
            # by the frontend collapse to a single set member.
            await client.sadd(PRIORITY_SET, anomaly_id)
        finally:
            await client.aclose()
    except Exception:  # noqa: BLE001
        _log.exception("priority bump failed for %s; falling back to LIFO", anomaly_id)


router = APIRouter(prefix="/api/v1")


# ---------- pagination cursor (opaque to frontend) ----------

def _encode_cursor(offset: int) -> str:
    payload = json.dumps({"offset": offset}).encode()
    return base64.urlsafe_b64encode(payload).decode()


def _decode_cursor(cursor: str | None) -> int:
    if not cursor:
        return 0
    try:
        decoded = base64.urlsafe_b64decode(cursor.encode())
        payload = json.loads(decoded)
        offset = int(payload["offset"])
        if offset < 0:
            raise ValueError("negative offset")
        return offset
    except (binascii.Error, json.JSONDecodeError, KeyError, TypeError, ValueError) as e:
        raise HTTPException(status_code=400, detail="Invalid cursor") from e


# ---------- /anomalies ----------

@router.delete("/anomalies", status_code=200)
async def clear_anomalies(
    pool: Annotated[asyncpg.Pool, Depends(get_pool)],
) -> dict[str, int]:
    """Wipe ALL anomalies + drift events + the priority queue. Used
    between demo runs so each /connect or /upload starts from a clean
    dashboard. Not for production.

    Specifically clears:
      * `anomalies` table (TRUNCATE)
      * `drift_events` table (TRUNCATE)
      * `anomalies:priority:set` Redis SET (DEL) — the new dedup'd
        priority queue
      * `anomalies:priority` Redis LIST (DEL) — legacy queue from
        before the LIST→SET migration; clear it so leftover entries
        from older runs don't re-enter via a stale subscriber

    Returns the count of DB rows deleted + the count of Redis priority
    members removed, so the caller can confirm the wipe took effect.
    """
    async with pool.acquire() as conn:
        deleted = await conn.fetchval("SELECT COUNT(*) FROM anomalies")
        await conn.execute("TRUNCATE anomalies, drift_events RESTART IDENTITY CASCADE")

    # Best-effort priority queue clear — Redis hiccup must NOT 500 the
    # wipe. The DB part already succeeded; the worker will drift on at
    # most a few stale priority entries before its own re-check kicks
    # them through to LIFO DB poll (which now finds an empty table).
    priority_cleared = 0
    try:
        url = os.environ.get("LOGGUARD_REDIS_URL", "redis://localhost:6379")
        client = redis_aio.from_url(url, decode_responses=True)
        try:
            # SCARD gives the count before deletion so the caller can
            # see what was cleared. DEL of a non-existent key is a no-op.
            priority_cleared = await client.scard("anomalies:priority:set") or 0
            await client.delete("anomalies:priority:set", "anomalies:priority")
        finally:
            await client.aclose()
    except Exception:  # noqa: BLE001
        _log.exception("priority-queue clear failed during DELETE /anomalies")

    return {
        "deleted": int(deleted or 0),
        "priority_cleared": int(priority_cleared),
    }


@router.get("/anomalies", response_model=AnomalyListResponse)
async def list_anomalies(
    pool: Annotated[asyncpg.Pool, Depends(get_pool)],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    since: Annotated[datetime | None, Query()] = None,
    severity: Annotated[Severity | None, Query()] = None,
    source: Annotated[
        str | None,
        Query(
            min_length=1, max_length=128,
            description=(
                "Exact-match filter on the `source` column — the parsed "
                "host/service identifier displayed in the UI (e.g. "
                "?source=bgl shows anomalies from the BGL upload)."
            ),
        ),
    ] = None,
    origin: Annotated[
        str | None,
        Query(
            min_length=1, max_length=32,
            description=(
                "Filter on the anomaly's origin tag. "
                "'user-upload' shows anomalies derived from /upload calls; "
                "'live-stream' shows anomalies from the live ingestion runner."
            ),
        ),
    ] = None,
    cursor: Annotated[str | None, Query()] = None,
) -> AnomalyListResponse:
    offset = _decode_cursor(cursor)
    # Normalise to UTC so naive timestamps don't compare against aware ones.
    since_aware = (
        since.replace(tzinfo=UTC) if since and since.tzinfo is None else since
    )
    items, total = await repository.list_anomalies(
        pool,
        limit=limit,
        offset=offset,
        severity=severity,
        since=since_aware,
        source=source,
        origin=origin,
    )
    next_offset = offset + len(items)
    next_cursor = _encode_cursor(next_offset) if next_offset < total else None
    return AnomalyListResponse(items=items, next_cursor=next_cursor)


@router.get("/anomalies/{anomaly_id}", response_model=Anomaly)
async def get_anomaly(
    anomaly_id: str,
    pool: Annotated[asyncpg.Pool, Depends(get_pool)],
) -> Anomaly:
    a = await repository.get_anomaly(pool, anomaly_id)
    if a is None:
        raise HTTPException(status_code=404, detail="Anomaly not found")
    return a


@router.get(
    "/anomalies/{anomaly_id}/explanation",
    response_model=Explanation,
    responses={
        202: {"description": "Explanation pending — poll or wait for websocket update"},
        404: {"description": "Anomaly not found"},
    },
)
async def get_explanation(
    anomaly_id: str,
    pool: Annotated[asyncpg.Pool, Depends(get_pool)],
) -> Explanation | Response:
    status_value, explanation = await repository.get_explanation(pool, anomaly_id)
    if status_value is None:
        raise HTTPException(status_code=404, detail="Anomaly not found")
    if status_value == "pending":
        # Bump this anomaly to the front of the explainer's priority
        # queue so the user clicking it doesn't wait through the entire
        # upload backlog. The RAG worker calls live LLaMA — expect the
        # 202 to flip to 200 in ~3-5s on GPU (llama3:8b) or ~30s on CPU.
        await _bump_explanation_priority(anomaly_id)
        return Response(status_code=status.HTTP_202_ACCEPTED)
    if explanation is None:
        # explanation_status is "failed" — no detail available. Surface as 500
        # for now; a richer error payload lands when the RAG worker arrives.
        raise HTTPException(status_code=500, detail="Explanation generation failed")
    return explanation


@router.post("/anomalies/{anomaly_id}/feedback", response_model=FeedbackResponse)
async def post_feedback(
    anomaly_id: str,
    body: FeedbackRequest,
    pool: Annotated[asyncpg.Pool, Depends(get_pool)],
) -> FeedbackResponse:
    updated = await repository.record_feedback(pool, anomaly_id, body.feedback)
    if not updated:
        raise HTTPException(status_code=404, detail="Anomaly not found")
    return FeedbackResponse(ok=True)


@router.get("/feedback", response_model=FeedbackHistoryResponse)
async def list_feedback(
    pool: Annotated[asyncpg.Pool, Depends(get_pool)],
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> FeedbackHistoryResponse:
    """List anomalies that have an engineer-supplied verdict, newest first.

    The engineer column is intentionally not in the response — multi-user
    auth + per-user attribution isn't modelled in the schema yet. The
    frontend can show the signed-in user's name where appropriate.
    """
    items, total, tp, fp = await repository.list_feedback(pool, limit=limit)
    return FeedbackHistoryResponse(
        items=[FeedbackHistoryItem(**it) for it in items],
        total=total,
        true_positive=tp,
        false_positive=fp,
    )


# ---------- /metrics ----------

@router.get("/metrics/summary", response_model=MetricsSummary)
async def metrics_summary(
    pool: Annotated[asyncpg.Pool, Depends(get_pool)],
) -> MetricsSummary:
    return await repository.metrics_summary(pool)


@router.get("/metrics/timeline", response_model=TimelineResponse)
async def metrics_timeline(
    window: Annotated[TimelineWindow, Query()],
    pool: Annotated[asyncpg.Pool, Depends(get_pool)],
) -> TimelineResponse:
    return await repository.metrics_timeline(pool, window)


# ---------- /system ----------

@router.get("/system/drift", response_model=DriftStatus)
async def system_drift(
    pool: Annotated[asyncpg.Pool, Depends(get_pool)],
) -> DriftStatus:
    return await repository.drift_status(pool)


# Hostnames the services-probe uses. Resolved at request time (not
# at module import) so test environments can override the env var
# between requests.
def _redis_url() -> str:
    return os.environ.get("LOGGUARD_REDIS_URL", "redis://localhost:6379")


def _ollama_url() -> str:
    return os.environ.get("LOGGUARD_LLAMA_HOST", "http://localhost:11434")


async def _probe_postgres(pool: asyncpg.Pool) -> SystemService:
    """Postgres health: SELECT 1 on a pooled connection.

    "online" if the query succeeds, "offline" otherwise. We don't
    have a "degraded" tier for Postgres in the demo (no slow-query /
    replication-lag instrumentation)."""
    try:
        async with pool.acquire() as conn:
            await conn.fetchval("SELECT 1")
        return SystemService(
            name="Postgres",
            status="online",
            detail="postgres:5432 · SELECT 1 OK",
        )
    except Exception as e:  # noqa: BLE001
        return SystemService(
            name="Postgres",
            status="offline",
            detail=f"connect failed: {type(e).__name__}",
        )


async def _probe_redis() -> SystemService:
    url = _redis_url()
    client = redis_aio.from_url(url, decode_responses=True)
    try:
        ok = await client.ping()
        return SystemService(
            name="Redis streams",
            status="online" if ok else "degraded",
            detail=f"{url} · PING OK" if ok else f"{url} · ping returned False",
        )
    except Exception as e:  # noqa: BLE001
        return SystemService(
            name="Redis streams",
            status="offline",
            detail=f"connect failed: {type(e).__name__}",
        )
    finally:
        try:
            await client.aclose()
        except Exception:  # noqa: BLE001
            pass


async def _probe_ollama() -> SystemService:
    """Ollama health: GET /api/tags via the existing OllamaClient.ping().

    Reuses the same client wrapper the RAG worker uses, so a positive
    probe here is meaningful — it's the exact same code path the
    explainer would use to call the model."""
    # Local import keeps `routes` from pulling rag/ at module scope.
    from rag.llama_client import OllamaClient
    client = OllamaClient()
    try:
        ok = await client.ping()
        model = client.model
        host = client.base_url
        return SystemService(
            name="Ollama / LLaMA",
            status="online" if ok else "offline",
            detail=(
                f"{host} · model: {model} · /api/tags OK"
                if ok else f"{host} · /api/tags failed"
            ),
        )
    except Exception as e:  # noqa: BLE001
        return SystemService(
            name="Ollama / LLaMA",
            status="offline",
            detail=f"connect failed: {type(e).__name__}",
        )
    finally:
        try:
            await client.aclose()
        except Exception:  # noqa: BLE001
            pass


# Module-level uptime anchor — set on import. Approximates the API's
# wall-clock uptime since boot (good enough for the System page; not
# meant to survive worker restarts in a multi-process deployment).
_STARTED_AT = time.monotonic()


@router.get("/system/services", response_model=SystemServicesResponse)
async def system_services(
    pool: Annotated[asyncpg.Pool, Depends(get_pool)],
) -> SystemServicesResponse:
    """Live health probes for the four backend services the System
    page surfaces. Probes run in parallel via asyncio.gather so a slow
    Ollama doesn't bottleneck the rest of the response.

    FastAPI itself is included as a trivially-online row — the fact
    that this handler responded is proof. Useful as a place to surface
    uptime so operators can confirm "the API I'm looking at is the
    one I redeployed".

    The RAG worker is intentionally omitted from this response — it's
    a daemon with no inbound port, so we can't probe it directly.
    Use the /system/queue endpoint to infer worker health from queue
    drain rate.
    """
    started_uptime_s = int(time.monotonic() - _STARTED_AT)
    api_row = SystemService(
        name="FastAPI backend",
        status="online",
        detail=f"localhost:8000 · uptime {started_uptime_s}s",
    )
    pg_row, redis_row, ollama_row = await asyncio.gather(
        _probe_postgres(pool),
        _probe_redis(),
        _probe_ollama(),
    )
    return SystemServicesResponse(items=[api_row, pg_row, redis_row, ollama_row])


@router.get("/system/queue", response_model=SystemQueueResponse)
async def system_queue(
    pool: Annotated[asyncpg.Pool, Depends(get_pool)],
) -> SystemQueueResponse:
    """Snapshot of the explanation queue: counts by status, plus the
    oldest pending row id and timestamp. The /admin/system page polls
    this so an operator can see at a glance whether the RAG worker is
    keeping up."""
    return await repository.system_queue_snapshot(pool)


# ---------- /training ----------

@router.get("/training/runs", response_model=TrainingRunsResponse)
async def training_runs(
    pool: Annotated[asyncpg.Pool, Depends(get_pool)],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> TrainingRunsResponse:
    """List historical training runs from the `training_runs` Postgres
    table, newest first. The /admin/training page consumes this; tests
    + CI populate the table; the API's `_seed_training_runs()` lifespan
    hook populates an initial pair on first boot.
    """
    items, active_id = await repository.list_training_runs(pool, limit=limit)
    return TrainingRunsResponse(items=items, active_id=active_id)
