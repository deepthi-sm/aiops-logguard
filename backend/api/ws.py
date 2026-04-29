"""
WebSocket handler for /api/v1/ws/anomalies.

Per the contract (api_contract.md), the server pushes canonical Anomaly objects
on detection plus a 30s heartbeat ping. In Step 4 this subscribes to the Redis
pubsub channel `anomalies:broadcast`. For PR 2 it sends a single stub anomaly
on connect followed by periodic pings, so Person B can wire up the client and
verify reconnect / heartbeat handling against a working endpoint.

Heartbeat interval is read at handler call time from `LOGGUARD_WS_PING_INTERVAL_S`
(default 30s) so tests can shrink it via monkeypatch without re-importing the module.
"""
import asyncio
import os

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from api import mock_data

router = APIRouter()


def _ping_interval_s() -> float:
    return float(os.environ.get("LOGGUARD_WS_PING_INTERVAL_S", "30"))


@router.websocket("/api/v1/ws/anomalies")
async def anomalies_ws(websocket: WebSocket) -> None:
    await websocket.accept()
    interval = _ping_interval_s()
    try:
        # Send the newest anomaly so the frontend has something to render
        # immediately on first connect — otherwise the dashboard would be
        # empty until the next real detection.
        newest = mock_data.all_anomalies()[0]
        await websocket.send_json(
            {"type": "anomaly", "data": newest.model_dump(mode="json")}
        )
        # Heartbeat loop. Server-push only — client messages are ignored
        # per contract. The handler exits when the client disconnects.
        while True:
            await asyncio.sleep(interval)
            await websocket.send_json({"type": "ping"})
    except WebSocketDisconnect:
        return
