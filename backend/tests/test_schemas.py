"""
Pydantic round-trip tests for the integration contract.

These guard against silent shape regressions — if any of these break, Person B's
generated TypeScript client is also likely to break. Treat failures here as a
contract change requiring a PR description flag (CLAUDE.md "How Claude Code
should work in this repo").
"""
from datetime import UTC, datetime

import pytest

from api.schemas import (
    Anomaly,
    AnomalyListResponse,
    ContributingLine,
    DriftStatus,
    Explanation,
    FeedbackRequest,
    HealthResponse,
    MetricsSummary,
    SimilarIncident,
    TimelineBucket,
    TimelineResponse,
)


def _base_anomaly_kwargs() -> dict:
    return {
        "id": "anom_2026-04-28T10:14:22_a1b2",
        "detected_at": datetime(2026, 4, 28, 10, 14, 22, tzinfo=UTC),
        "severity": "critical",
        "source": "namenode-prod-3",
        "ensemble_score": 0.92,
        "confidence": 0.87,
        "failure_probability": 0.78,
        "predicted_failure_window_min": 12,
        "log_template": "ERROR blk_* NameNode connection refused from *",
        "sequence_preview": ["a", "b", "c"],
        "top_contributing_lines": [ContributingLine(line="x", attention=0.1)],
        "explanation_status": "ready",
        "cluster_id": "clu_77",
        "cluster_size": 14,
    }


def test_anomaly_round_trip_preserves_fields():
    obj = Anomaly(**_base_anomaly_kwargs())
    dumped = obj.model_dump(mode="json")
    restored = Anomaly.model_validate(dumped)
    assert restored.model_dump(mode="json") == dumped


def test_anomaly_timestamp_serializes_with_z_suffix():
    obj = Anomaly(**_base_anomaly_kwargs())
    assert obj.model_dump(mode="json")["detected_at"] == "2026-04-28T10:14:22Z"


def test_anomaly_severity_rejects_unknown_value():
    kwargs = _base_anomaly_kwargs()
    kwargs["severity"] = "banana"
    with pytest.raises(ValueError):
        Anomaly(**kwargs)


def test_anomaly_explanation_status_rejects_unknown_value():
    kwargs = _base_anomaly_kwargs()
    kwargs["explanation_status"] = "almost_ready"
    with pytest.raises(ValueError):
        Anomaly(**kwargs)


def test_anomaly_score_bounds_enforced():
    kwargs = _base_anomaly_kwargs()
    kwargs["ensemble_score"] = 1.5  # > 1.0
    with pytest.raises(ValueError):
        Anomaly(**kwargs)


def test_predicted_failure_window_can_be_null():
    kwargs = _base_anomaly_kwargs()
    kwargs["predicted_failure_window_min"] = None
    obj = Anomaly(**kwargs)
    assert obj.model_dump(mode="json")["predicted_failure_window_min"] is None


def test_anomaly_list_response_with_no_cursor_is_last_page():
    obj = AnomalyListResponse(items=[Anomaly(**_base_anomaly_kwargs())], next_cursor=None)
    assert obj.model_dump(mode="json")["next_cursor"] is None


def test_feedback_request_rejects_unknown_value():
    with pytest.raises(ValueError):
        FeedbackRequest(feedback="maybe")  # type: ignore[arg-type]


def test_drift_status_rejects_unknown_status():
    with pytest.raises(ValueError):
        DriftStatus(
            drift_score=0.1,
            last_retrain=None,
            status="ok",  # type: ignore[arg-type]
            psi_score=0.05,
        )


def test_explanation_round_trip():
    obj = Explanation(
        root_cause="rc",
        recommended_fix="fix",
        similar_incidents=[
            SimilarIncident(
                incident_id="inc_1",
                template="t",
                resolved_at=datetime(2024, 1, 1, tzinfo=UTC),
                similarity_score=0.5,
            ),
        ],
        attention_weights=[0.1, 0.2],
    )
    dumped = obj.model_dump(mode="json")
    assert dumped["similar_incidents"][0]["resolved_at"] == "2024-01-01T00:00:00Z"
    Explanation.model_validate(dumped)


def test_metrics_summary_round_trip():
    obj = MetricsSummary(
        total_24h=10,
        critical_24h=1,
        warning_24h=3,
        info_24h=6,
        avg_confidence=0.7,
        drift_score=0.1,
        last_retrain=datetime(2026, 4, 25, 3, 0, 0, tzinfo=UTC),
    )
    dumped = obj.model_dump(mode="json")
    MetricsSummary.model_validate(dumped)
    assert dumped["last_retrain"] == "2026-04-25T03:00:00Z"


def test_timeline_response_round_trip():
    obj = TimelineResponse(
        window="1h",
        buckets=[
            TimelineBucket(
                ts=datetime(2026, 4, 28, 10, 0, 0, tzinfo=UTC),
                critical=0,
                warning=1,
                info=3,
            ),
        ],
    )
    dumped = obj.model_dump(mode="json")
    TimelineResponse.model_validate(dumped)
    assert dumped["buckets"][0]["ts"] == "2026-04-28T10:00:00Z"


def test_health_response_uptime_must_be_non_negative():
    HealthResponse(status="ok", version="0.1.0", uptime_s=0)
    with pytest.raises(ValueError):
        HealthResponse(status="ok", version="0.1.0", uptime_s=-1)
