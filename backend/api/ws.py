"""
WebSocket handler for /api/v1/ws/anomalies.

Subscribes each connected client to the Redis pubsub channel
`anomalies:broadcast` and forwards every message verbatim. The
ingestion runner (`ingestion.runner.IngestionRunner._publish`) is the
sole writer; this handler is a fan-out reader.

Lifecycle per connection:
  1. accept()
  2. send the newest persisted anomaly so a freshly-loaded dashboard
     has something to render before the next live event arrives
     (skips quietly if the DB is empty or unconfigured — `/health`
     style probes still see a working WS).
  3. concurrently:
       - forward pubsub messages on `anomalies:broadcast`
       - emit a {"type": "ping"} every LOGGUARD_WS_PING_INTERVAL_S
  4. clean up pubsub + redis client when the client disconnects.

If Redis is unreachable the connection still serves heartbeats —
useful in dev where the runner isn't always running. The handler
logs a warning and skips the broadcast subscription in that case.
"""
from __future__ import annotations

import asyncio
import logging
import os

import redis.asyncio as redis_aio
from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect

from api import repository
from api.db import get_pool
from ingestion.runner import CHANNEL_BROADCAST

router = APIRouter()
log = logging.getLogger(__name__)

DEFAULT_PING_INTERVAL_S = 30.0


def _ping_interval_s() -> float:
    return float(
        os.environ.get("LOGGUARD_WS_PING_INTERVAL_S", str(DEFAULT_PING_INTERVAL_S))
    )


def _redis_url() -> str:
    return os.environ.get("LOGGUARD_REDIS_URL", "redis://localhost:6379")


@router.websocket("/api/v1/ws/anomalies")
async def anomalies_ws(websocket: WebSocket) -> None:
    await websocket.accept()
    pool = _try_get_pool(websocket)

    # 1. Initial frame — newest persisted anomaly so the dashboard has
    #    something to render on connect. Skip silently if no DB or no rows.
    if pool is not None:
        try:
            newest = await repository.get_newest_anomaly(pool)
        except Exception:  # noqa: BLE001
            log.exception("ws: failed to fetch newest anomaly for initial frame")
            newest = None
        if newest is not None:
            await websocket.send_json(
                {"type": "anomaly", "data": newest.model_dump(mode="json")}
            )

    # 2. Concurrently: forward pubsub messages + emit heartbeats.
    pubsub_client, pubsub = await _try_subscribe()
    forward_task = asyncio.create_task(_forward_pubsub(pubsub, websocket))
    ping_task = asyncio.create_task(_ping_loop(websocket))
    try:
        # Whichever task finishes first (typically WebSocketDisconnect
        # raised inside one of them) unblocks us; we then cancel the
        # other and clean up.
        done, pending = await asyncio.wait(
            {forward_task, ping_task},
            return_when=asyncio.FIRST_COMPLETED,
        )
        for t in pending:
            t.cancel()
        # Surface a real exception (other than disconnect / cancellation)
        # so we don't swallow bugs.
        for t in done:
            exc = t.exception()
            if exc is not None and not isinstance(exc, WebSocketDisconnect | asyncio.CancelledError):
                raise exc
    except WebSocketDisconnect:
        pass
    finally:
        forward_task.cancel()
        ping_task.cancel()
        await _safe_unsubscribe(pubsub)
        await _safe_close_redis(pubsub_client)


# -- helpers ----------------------------------------------------------------


def _try_get_pool(websocket: WebSocket):
    """Pull the pool off `app.state` directly. We can't use `Depends`
    here for the initial frame because dependency resolution returns
    HTTPException on missing pool — we want graceful degradation,
    not a 503-equivalent on a WS connection."""
    return getattr(websocket.app.state, "pool", None)


# Keep get_pool importable so dependency_overrides patterns still work
# for tests that want to inject a fake pool.
_ = Depends, get_pool


async def _try_subscribe() -> tuple[redis_aio.Redis | None, object | None]:
    """Best-effort Redis pubsub subscription. Returns (None, None) when
    Redis isn't reachable so the handler still serves heartbeats."""
    url = _redis_url()
    try:
        client = redis_aio.from_url(url, decode_responses=True)
        # `from_url` is lazy — actually round-trip to confirm connectivity
        # so we don't hang on the first message.
        await client.ping()
        pubsub = client.pubsub()
        await pubsub.subscribe(CHANNEL_BROADCAST)
        return client, pubsub
    except Exception:  # noqa: BLE001
        log.warning(
            "ws: redis pubsub at %s unreachable — running heartbeat-only", url
        )
        return None, None


async def _forward_pubsub(pubsub, websocket: WebSocket) -> None:
    """Forward each `anomalies:broadcast` message to the client.

    Iterates pubsub.listen() forever; cancellation from the outer
    handler tears it down on disconnect."""
    if pubsub is None:
        # No subscription — block forever (cancellation will free us).
        await asyncio.Event().wait()
        return
    async for message in pubsub.listen():
        if message.get("type") != "message":
            continue
        # Runner publishes the Anomaly as a JSON string; the WS contract
        # wraps it in {"type": "anomaly", "data": ...}. Send as text so
        # we don't double-encode.
        data = message["data"]
        await websocket.send_json({"type": "anomaly", "data": _decode_payload(data)})


def _decode_payload(payload):
    """Pubsub payload is a JSON-encoded Anomaly. The frontend expects
    `data` to be the parsed object, not a string — so json.loads it
    here and let send_json re-encode the whole envelope."""
    import json

    if isinstance(payload, bytes | bytearray):
        payload = payload.decode("utf-8", errors="replace")
    return json.loads(payload)


async def _ping_loop(websocket: WebSocket) -> None:
    interval = _ping_interval_s()
    while True:
        await asyncio.sleep(interval)
        await websocket.send_json({"type": "ping"})


async def _safe_unsubscribe(pubsub) -> None:
    if pubsub is None:
        return
    try:
        await pubsub.unsubscribe(CHANNEL_BROADCAST)
        await pubsub.aclose()
    except Exception:  # noqa: BLE001
        pass


async def _safe_close_redis(client: redis_aio.Redis | None) -> None:
    if client is None:
        return
    try:
        await client.aclose()
    except Exception:  # noqa: BLE001
        pass
