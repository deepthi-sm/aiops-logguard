"""
WebSocket smoke tests for /api/v1/ws/anomalies.

The handler now:
  1. Sends the newest persisted anomaly as the initial frame (Step 4b-iii).
  2. Subscribes to the `anomalies:broadcast` Redis pubsub and forwards
     every message to the client.
  3. Emits {"type": "ping"} every LOGGUARD_WS_PING_INTERVAL_S.

These tests pin (1) and (3) against the seeded test database (the
`client` fixture from conftest). The pubsub forwarding path (2) is
covered indirectly — `test_runner.py` pins what the runner publishes,
and the unit tests for `_decode_payload` keep the framing on-contract.
A real Redis-pubsub end-to-end test belongs in a CI integration job
once the runner is deployed alongside the API.
"""
import pytest

from api.schemas import Anomaly


@pytest.fixture(autouse=True)
def fast_pings(monkeypatch):
    """Shrink the heartbeat interval to ~50ms so the heartbeat path is
    exercised in well under a second instead of the production 30s."""
    monkeypatch.setenv("LOGGUARD_WS_PING_INTERVAL_S", "0.05")


@pytest.fixture(autouse=True)
def isolate_redis(monkeypatch):
    """Point the WS at an unreachable Redis port so it falls back to
    heartbeat-only — the handler explicitly handles this case (the
    runner isn't running during these tests). Tests that need real
    pubsub forwarding live in an integration suite."""
    monkeypatch.setenv("LOGGUARD_REDIS_URL", "redis://127.0.0.1:1")


def test_ws_initial_frame_is_anomaly_in_contract_shape(client):
    """First message must be an Anomaly — the seeded fixture has at
    least one row, so the handler reads the newest and pushes it."""
    with client.websocket_connect("/api/v1/ws/anomalies") as ws:
        msg = ws.receive_json()
        assert msg["type"] == "anomaly"
        Anomaly.model_validate(msg["data"])


def test_ws_sends_periodic_ping_heartbeat(client):
    """After the initial anomaly frame, the next message should be the
    {'type': 'ping'} heartbeat (or another pubsub anomaly — but with
    Redis unreachable in this test, only pings can arrive)."""
    with client.websocket_connect("/api/v1/ws/anomalies") as ws:
        # Drop the initial anomaly frame.
        ws.receive_json()
        # Next frame is the heartbeat ping (Redis is unreachable so
        # pubsub forwarding is dormant).
        msg = ws.receive_json()
        assert msg == {"type": "ping"}
