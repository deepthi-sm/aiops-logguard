"""
WebSocket smoke tests for /api/v1/ws/anomalies.

The handler reads the heartbeat interval from LOGGUARD_WS_PING_INTERVAL_S at
call time, so the autouse fixture can shrink it to ~50ms — the heartbeat path
is exercised in well under a second instead of the production 30s.
"""
import pytest
from fastapi.testclient import TestClient

from api.main import app
from api.schemas import Anomaly


@pytest.fixture(autouse=True)
def fast_pings(monkeypatch):
    monkeypatch.setenv("LOGGUARD_WS_PING_INTERVAL_S", "0.05")


def test_ws_initial_frame_is_anomaly_in_contract_shape():
    with TestClient(app) as client:
        with client.websocket_connect("/api/v1/ws/anomalies") as ws:
            msg = ws.receive_json()
            assert msg["type"] == "anomaly"
            Anomaly.model_validate(msg["data"])


def test_ws_sends_periodic_ping_heartbeat():
    with TestClient(app) as client:
        with client.websocket_connect("/api/v1/ws/anomalies") as ws:
            # Drop the initial anomaly frame.
            ws.receive_json()
            # Next frame should be the heartbeat ping.
            msg = ws.receive_json()
            assert msg == {"type": "ping"}
