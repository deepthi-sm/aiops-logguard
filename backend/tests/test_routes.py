"""
End-to-end shape tests for every REST endpoint in the contract.

Each test calls through TestClient → FastAPI handler → asyncpg pool →
seeded test database, then validates the response against the same
Pydantic model the handler declares. The `client` fixture comes from
`tests/conftest.py` and arrives with the canonical mock fixtures
already inserted, so the existing assertions still hold against the
real SQL path.

Tests in this file require Postgres; the conftest skips them cleanly
when `LOGGUARD_DB_URL` isn't set (CI sets it, see ci.yml).
"""
import re

import pytest

from api import mock_data
from api.schemas import (
    Anomaly,
    AnomalyListResponse,
    DriftStatus,
    Explanation,
    FeedbackResponse,
    MetricsSummary,
    TimelineResponse,
)

# ---------- GET /anomalies (list) ----------

def test_list_anomalies_returns_all_under_default_limit(client):
    r = client.get("/api/v1/anomalies")
    assert r.status_code == 200
    body = r.json()
    AnomalyListResponse.model_validate(body)
    assert len(body["items"]) == len(mock_data.all_anomalies())
    assert body["next_cursor"] is None


def test_list_anomalies_sorted_newest_first(client):
    r = client.get("/api/v1/anomalies")
    timestamps = [it["detected_at"] for it in r.json()["items"]]
    assert timestamps == sorted(timestamps, reverse=True)


def test_list_anomalies_severity_filter(client):
    r = client.get("/api/v1/anomalies?severity=critical")
    items = r.json()["items"]
    assert len(items) >= 1
    assert all(it["severity"] == "critical" for it in items)


def test_list_anomalies_invalid_severity_rejected(client):
    r = client.get("/api/v1/anomalies?severity=banana")
    assert r.status_code == 422


def test_list_anomalies_pagination_round_trip(client):
    r1 = client.get("/api/v1/anomalies?limit=2")
    body1 = r1.json()
    assert len(body1["items"]) == 2
    assert body1["next_cursor"] is not None

    r2 = client.get(f"/api/v1/anomalies?limit=2&cursor={body1['next_cursor']}")
    body2 = r2.json()

    ids_page1 = {it["id"] for it in body1["items"]}
    ids_page2 = {it["id"] for it in body2["items"]}
    assert ids_page1.isdisjoint(ids_page2)


def test_list_anomalies_invalid_cursor_returns_400(client):
    r = client.get("/api/v1/anomalies?cursor=not-base64-at-all!!!")
    assert r.status_code == 400


def test_list_anomalies_since_filter(client):
    cutoff = "2026-04-28T09:30:00Z"
    r = client.get(f"/api/v1/anomalies?since={cutoff}")
    assert r.status_code == 200
    items = r.json()["items"]
    # Cutoff sits between fixture clusters — at least some, but not all, pass.
    assert 0 < len(items) < len(mock_data.all_anomalies())
    assert all(it["detected_at"] > cutoff for it in items)


def test_list_anomalies_limit_bounds_enforced(client):
    assert client.get("/api/v1/anomalies?limit=0").status_code == 422
    assert client.get("/api/v1/anomalies?limit=201").status_code == 422


# ---------- GET /anomalies/{id} ----------

def test_get_anomaly_found_round_trip(client):
    target = mock_data.all_anomalies()[0]
    r = client.get(f"/api/v1/anomalies/{target.id}")
    assert r.status_code == 200
    Anomaly.model_validate(r.json())
    assert r.json()["id"] == target.id


def test_get_anomaly_not_found(client):
    r = client.get("/api/v1/anomalies/anom_does_not_exist")
    assert r.status_code == 404
    assert r.json()["detail"] == "Anomaly not found"


# ---------- GET /anomalies/{id}/explanation ----------

def test_get_explanation_ready_returns_200_and_valid_shape(client):
    target = next(a for a in mock_data.all_anomalies() if a.explanation_status == "ready")
    r = client.get(f"/api/v1/anomalies/{target.id}/explanation")
    assert r.status_code == 200
    Explanation.model_validate(r.json())


def test_get_explanation_pending_returns_202(client):
    target = next(a for a in mock_data.all_anomalies() if a.explanation_status == "pending")
    r = client.get(f"/api/v1/anomalies/{target.id}/explanation")
    assert r.status_code == 202


def test_get_explanation_404_for_missing_anomaly(client):
    r = client.get("/api/v1/anomalies/anom_nope/explanation")
    assert r.status_code == 404


# ---------- GET /metrics/summary ----------

def test_metrics_summary_shape(client):
    r = client.get("/api/v1/metrics/summary")
    assert r.status_code == 200
    MetricsSummary.model_validate(r.json())


# ---------- GET /metrics/timeline ----------

@pytest.mark.parametrize("window,expected_buckets", [("1h", 60), ("24h", 96), ("7d", 168)])
def test_metrics_timeline_bucket_count(client, window, expected_buckets):
    r = client.get(f"/api/v1/metrics/timeline?window={window}")
    assert r.status_code == 200
    body = r.json()
    TimelineResponse.model_validate(body)
    assert body["window"] == window
    assert len(body["buckets"]) == expected_buckets


def test_metrics_timeline_invalid_window_rejected(client):
    r = client.get("/api/v1/metrics/timeline?window=42d")
    assert r.status_code == 422


def test_metrics_timeline_window_required(client):
    r = client.get("/api/v1/metrics/timeline")
    assert r.status_code == 422


# ---------- GET /system/drift ----------

def test_system_drift_shape(client):
    r = client.get("/api/v1/system/drift")
    assert r.status_code == 200
    DriftStatus.model_validate(r.json())


# ---------- POST /anomalies/{id}/feedback ----------

def test_post_feedback_true_positive(client):
    target = mock_data.all_anomalies()[0]
    r = client.post(
        f"/api/v1/anomalies/{target.id}/feedback",
        json={"feedback": "true_positive"},
    )
    assert r.status_code == 200
    body = r.json()
    FeedbackResponse.model_validate(body)
    assert body["ok"] is True


def test_post_feedback_false_positive(client):
    target = mock_data.all_anomalies()[0]
    r = client.post(
        f"/api/v1/anomalies/{target.id}/feedback",
        json={"feedback": "false_positive"},
    )
    assert r.status_code == 200


def test_post_feedback_invalid_value_422(client):
    target = mock_data.all_anomalies()[0]
    r = client.post(
        f"/api/v1/anomalies/{target.id}/feedback",
        json={"feedback": "maybe"},
    )
    assert r.status_code == 422


def test_post_feedback_404_for_missing_anomaly(client):
    r = client.post(
        "/api/v1/anomalies/anom_nope/feedback",
        json={"feedback": "true_positive"},
    )
    assert r.status_code == 404


# ---------- timestamp format (contract: ISO 8601 UTC with 'Z' suffix) ----------

def test_anomaly_timestamps_use_z_suffix(client):
    r = client.get("/api/v1/anomalies")
    pattern = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
    for it in r.json()["items"]:
        assert pattern.match(it["detected_at"]), f"bad timestamp: {it['detected_at']}"


def test_metrics_summary_timestamp_uses_z_suffix(client):
    r = client.get("/api/v1/metrics/summary")
    body = r.json()
    if body["last_retrain"] is not None:
        assert re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$", body["last_retrain"])


# ---------- /openapi.json publishes the full contract ----------

def test_openapi_publishes_every_contract_path(client):
    r = client.get("/openapi.json")
    assert r.status_code == 200
    paths = r.json()["paths"]
    # The paths Person B's generated client expects to exist.
    expected = [
        "/api/v1/health",
        "/api/v1/anomalies",
        "/api/v1/anomalies/{anomaly_id}",
        "/api/v1/anomalies/{anomaly_id}/explanation",
        "/api/v1/anomalies/{anomaly_id}/feedback",
        "/api/v1/metrics/summary",
        "/api/v1/metrics/timeline",
        "/api/v1/system/drift",
    ]
    for p in expected:
        assert p in paths, f"openapi missing path {p}"


def test_openapi_contains_anomaly_schema(client):
    spec = client.get("/openapi.json").json()
    assert "Anomaly" in spec["components"]["schemas"]
    anomaly_schema = spec["components"]["schemas"]["Anomaly"]
    # Every canonical field per CLAUDE.md "Canonical anomaly shape"
    expected_fields = {
        "id",
        "detected_at",
        "severity",
        "source",
        "ensemble_score",
        "confidence",
        "failure_probability",
        "predicted_failure_window_min",
        "log_template",
        "sequence_preview",
        "top_contributing_lines",
        "explanation_status",
        "cluster_id",
        "cluster_size",
    }
    assert set(anomaly_schema["properties"].keys()) == expected_fields
