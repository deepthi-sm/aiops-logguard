"""
In-memory fixtures for the stub REST + WS handlers (Step 2 of CLAUDE.md
"Build order"). The instant /openapi.json publishes from these shapes,
Person B can codegen her TypeScript client and start integration; her
frontend never has to know these are mocks.

Replaced wholesale by DB-backed queries in Step 4. Kept in its own module
so tests can import the same fixtures the routes serve and assert against
known values.
"""
from datetime import UTC, datetime, timedelta

from api.schemas import (
    Anomaly,
    ContributingLine,
    DriftStatus,
    Explanation,
    MetricsSummary,
    SimilarIncident,
    TimelineBucket,
    TimelineResponse,
    TimelineWindow,
)

# Fixed reference time so fixtures are deterministic and tests can assert
# against known timestamps.
_REF = datetime(2026, 4, 28, 10, 14, 22, tzinfo=UTC)
_LAST_RETRAIN = datetime(2026, 4, 25, 3, 0, 0, tzinfo=UTC)


_ANOMALIES: list[Anomaly] = [
    Anomaly(
        id="anom_2026-04-28T10:14:22_a1b2",
        detected_at=_REF,
        severity="critical",
        source="namenode-prod-3",
        origin="live-stream",
        ensemble_score=0.92,
        confidence=0.87,
        failure_probability=0.78,
        predicted_failure_window_min=12,
        log_template="ERROR blk_* NameNode connection refused from *",
        sequence_preview=[
            "INFO blk_8473628 receiving block from /10.0.1.42",
            "WARN blk_8473628 slow read from /10.0.1.42",
            "ERROR blk_8473628 NameNode connection refused from /10.0.1.42",
        ],
        top_contributing_lines=[
            ContributingLine(
                line="ERROR blk_8473628 NameNode connection refused from /10.0.1.42",
                attention=0.31,
            ),
            ContributingLine(
                line="WARN blk_8473628 slow read from /10.0.1.42",
                attention=0.22,
            ),
            ContributingLine(
                line="ERROR blk_8473628 NameNode connection refused from /10.0.1.43",
                attention=0.18,
            ),
        ],
        explanation_status="ready",
        cluster_id="clu_77",
        cluster_size=14,
    ),
    Anomaly(
        id="anom_2026-04-28T10:08:11_b3c4",
        detected_at=_REF - timedelta(minutes=6),
        severity="warning",
        source="datanode-prod-7",
        origin="live-stream",
        ensemble_score=0.74,
        confidence=0.71,
        failure_probability=0.42,
        predicted_failure_window_min=None,
        log_template="WARN blk_* slow disk write threshold exceeded *",
        sequence_preview=[
            "INFO blk_2284411 received block",
            "WARN blk_2284411 slow disk write threshold exceeded 200ms",
        ],
        top_contributing_lines=[
            ContributingLine(
                line="WARN blk_2284411 slow disk write threshold exceeded 200ms",
                attention=0.27,
            ),
        ],
        explanation_status="ready",
        cluster_id="clu_42",
        cluster_size=3,
    ),
    Anomaly(
        id="anom_2026-04-28T09:51:03_c5d6",
        detected_at=_REF - timedelta(minutes=23),
        severity="warning",
        source="namenode-prod-1",
        origin="live-stream",
        ensemble_score=0.68,
        confidence=0.62,
        failure_probability=0.38,
        predicted_failure_window_min=None,
        log_template="WARN heartbeat lost from *",
        sequence_preview=[
            "INFO heartbeat from datanode-7",
            "WARN heartbeat lost from datanode-7",
        ],
        top_contributing_lines=[
            ContributingLine(line="WARN heartbeat lost from datanode-7", attention=0.19),
        ],
        # "pending" exercises the 202 path on /explanation. Frontend uses this
        # to verify its loading-state UX.
        explanation_status="pending",
        cluster_id="clu_42",
        cluster_size=3,
    ),
    Anomaly(
        id="anom_2026-04-28T09:32:55_d7e8",
        detected_at=_REF - timedelta(minutes=41),
        severity="info",
        source="datanode-prod-2",
        origin="live-stream",
        ensemble_score=0.41,
        confidence=0.55,
        failure_probability=0.12,
        predicted_failure_window_min=None,
        log_template="INFO PacketResponder * for block * terminating",
        sequence_preview=[
            "INFO PacketResponder 1 for block blk_3 terminating",
        ],
        top_contributing_lines=[
            ContributingLine(
                line="INFO PacketResponder 1 for block blk_3 terminating",
                attention=0.08,
            ),
        ],
        explanation_status="ready",
        cluster_id="clu_03",
        cluster_size=27,
    ),
    Anomaly(
        id="anom_2026-04-28T09:01:18_e9f0",
        detected_at=_REF - timedelta(minutes=73),
        severity="info",
        source="datanode-prod-4",
        origin="live-stream",
        ensemble_score=0.36,
        confidence=0.51,
        failure_probability=0.08,
        predicted_failure_window_min=None,
        log_template="INFO Verification succeeded for block *",
        sequence_preview=[
            "INFO Verification succeeded for block blk_8473100",
        ],
        top_contributing_lines=[
            ContributingLine(
                line="INFO Verification succeeded for block blk_8473100",
                attention=0.05,
            ),
        ],
        explanation_status="ready",
        cluster_id="clu_03",
        cluster_size=27,
    ),
    Anomaly(
        id="anom_2026-04-28T08:42:09_f1a2",
        detected_at=_REF - timedelta(minutes=92),
        severity="info",
        source="datanode-prod-9",
        origin="live-stream",
        ensemble_score=0.33,
        confidence=0.49,
        failure_probability=0.05,
        predicted_failure_window_min=None,
        log_template="INFO blk_* size * received from *",
        sequence_preview=[
            "INFO blk_8470001 size 67108864 received from /10.0.1.45",
        ],
        top_contributing_lines=[
            ContributingLine(
                line="INFO blk_8470001 size 67108864 received from /10.0.1.45",
                attention=0.04,
            ),
        ],
        explanation_status="ready",
        cluster_id="clu_03",
        cluster_size=27,
    ),
]


_EXPLANATIONS: dict[str, Explanation] = {
    "anom_2026-04-28T10:14:22_a1b2": Explanation(
        root_cause=(
            "High reconstruction error in NameNode connection logs. "
            "Pattern matches connection pool exhaustion seen in incident #247."
        ),
        recommended_fix=(
            "1. Check NameNode connection pool config\n"
            "2. Review recent traffic spike\n"
            "3. Restart NameNode service if pool is saturated"
        ),
        similar_incidents=[
            SimilarIncident(
                incident_id="inc_247",
                template="ERROR blk_* NameNode connection refused from *",
                resolved_at=datetime(2024, 1, 15, 14, 32, 11, tzinfo=UTC),
                similarity_score=0.91,
            ),
            SimilarIncident(
                incident_id="inc_198",
                template="ERROR NameNode IPC handler queue full",
                resolved_at=datetime(2024, 7, 9, 22, 11, 5, tzinfo=UTC),
                similarity_score=0.78,
            ),
        ],
        attention_weights=[0.31, 0.28, 0.15, 0.09, 0.07, 0.05, 0.05],
    ),
    "anom_2026-04-28T10:08:11_b3c4": Explanation(
        root_cause=(
            "Disk write latency on datanode-prod-7 exceeds normal envelope. "
            "Likely IO contention from concurrent block replication."
        ),
        recommended_fix=(
            "1. Check disk IO queue depth on datanode-prod-7\n"
            "2. Throttle replication if active\n"
            "3. If sustained, rotate writes to a healthier datanode"
        ),
        similar_incidents=[
            SimilarIncident(
                incident_id="inc_312",
                template="WARN blk_* slow disk write threshold exceeded *",
                resolved_at=datetime(2025, 2, 21, 8, 4, 33, tzinfo=UTC),
                similarity_score=0.83,
            ),
        ],
        attention_weights=[0.27, 0.18, 0.11, 0.09],
    ),
    "anom_2026-04-28T09:32:55_d7e8": Explanation(
        root_cause=(
            "Routine PacketResponder lifecycle event. Frequency slightly above "
            "baseline but within healthy operating range."
        ),
        recommended_fix="No action required. Continue monitoring.",
        similar_incidents=[],
        attention_weights=[0.08, 0.05, 0.04],
    ),
    "anom_2026-04-28T09:01:18_e9f0": Explanation(
        root_cause="Block verification completed successfully. Informational only.",
        recommended_fix="No action required.",
        similar_incidents=[],
        attention_weights=[0.05, 0.03],
    ),
    "anom_2026-04-28T08:42:09_f1a2": Explanation(
        root_cause="Standard block ingest. Informational only.",
        recommended_fix="No action required.",
        similar_incidents=[],
        attention_weights=[0.04, 0.03],
    ),
    # The "pending" anomaly intentionally has no entry here so that path
    # of the /explanation handler stays exercised against real data.
}


def all_anomalies() -> list[Anomaly]:
    """Newest-first, matching the real /api/v1/anomalies query order."""
    return sorted(_ANOMALIES, key=lambda a: a.detected_at, reverse=True)


def find_anomaly(anomaly_id: str) -> Anomaly | None:
    return next((a for a in _ANOMALIES if a.id == anomaly_id), None)


def explanation_for(anomaly_id: str) -> Explanation | None:
    """None if the anomaly's explanation isn't ready (caller should 202)."""
    return _EXPLANATIONS.get(anomaly_id)


def metrics_summary() -> MetricsSummary:
    items = _ANOMALIES
    return MetricsSummary(
        total_24h=len(items),
        critical_24h=sum(1 for a in items if a.severity == "critical"),
        warning_24h=sum(1 for a in items if a.severity == "warning"),
        info_24h=sum(1 for a in items if a.severity == "info"),
        avg_confidence=round(sum(a.confidence for a in items) / len(items), 3),
        drift_score=0.12,
        last_retrain=_LAST_RETRAIN,
    )


def drift_status() -> DriftStatus:
    return DriftStatus(
        drift_score=0.12,
        last_retrain=_LAST_RETRAIN,
        status="healthy",
        psi_score=0.08,
    )


def timeline(window: TimelineWindow) -> TimelineResponse:
    """Bucket sizes per the contract (api_contract.md /metrics/timeline):
    1h → 60×1m, 24h → 96×15m, 7d → 168×1h.
    """
    if window == "1h":
        bucket_count = 60
        bucket_step = timedelta(minutes=1)
    elif window == "24h":
        bucket_count = 96
        bucket_step = timedelta(minutes=15)
    else:  # "7d"
        bucket_count = 168
        bucket_step = timedelta(hours=1)

    end = _REF.replace(microsecond=0)
    start = end - bucket_step * (bucket_count - 1)
    buckets: list[TimelineBucket] = []
    for i in range(bucket_count):
        ts = start + bucket_step * i
        # Synthetic counts so the chart has texture: critical sparse,
        # warning periodic, info common.
        critical = 1 if i % 30 == 7 else 0
        warning = 2 if i % 5 == 0 else 0
        info = 3 if i % 2 == 0 else 1
        buckets.append(TimelineBucket(ts=ts, critical=critical, warning=warning, info=info))
    return TimelineResponse(window=window, buckets=buckets)
