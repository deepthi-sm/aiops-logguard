"""
Tests for `ml.postprocess` — severity scoring, dedup, and Anomaly building.
"""
from datetime import UTC, datetime, timedelta

import pytest

from api.schemas import Anomaly
from ingestion.sequence_builder import ParsedLog, build_windows
from ml.detector import DetectionResult
from ml.postprocess import (
    AnomalyContext,
    Deduplicator,
    build_anomaly,
    decide_severity,
    new_anomaly_id,
)
from ml.transformer import WINDOW_LEN

# -- shared helpers --------------------------------------------------------


def _events(n: int, source: str = "host-1") -> list[ParsedLog]:
    return [
        ParsedLog(
            raw=f"INFO line {i}",
            template=f"INFO template_{i % 3}",
            template_id=str(i % 3),
            source=source,
            line_no=i,
        )
        for i in range(n)
    ]


def _detection(
    *,
    transformer_prob: float = 0.5,
    ae_error_norm: float = 0.5,
    ensemble: float = 0.5,
    confidence: float = 0.5,
    failure_min: int = 7,
) -> DetectionResult:
    return DetectionResult(
        ensemble_score=ensemble,
        transformer_prob=transformer_prob,
        ae_error_raw=0.0,
        ae_error_normalised=ae_error_norm,
        confidence=confidence,
        predicted_failure_minutes=failure_min,
        attention=tuple([1.0 / WINDOW_LEN] * WINDOW_LEN),
    )


# -- decide_severity --------------------------------------------------------


class TestDecideSeverity:
    def test_critical_when_failure_prob_high_and_source_in_critical_set(self):
        det = _detection(transformer_prob=0.9)
        assert (
            decide_severity(det, "nova-api-prod-3", critical_sources=frozenset({"nova-api-prod-3"}))
            == "critical"
        )

    def test_high_failure_prob_alone_is_not_critical(self):
        """The source must be in the critical set; otherwise we step down to
        warning/info."""
        det = _detection(transformer_prob=0.9, ensemble=0.9)
        assert decide_severity(det, "some-other-host") == "warning"

    def test_warning_when_ensemble_high(self):
        det = _detection(ensemble=0.9, transformer_prob=0.5)
        assert decide_severity(det, "host-1") == "warning"

    def test_info_when_neither_rule_fires(self):
        det = _detection(ensemble=0.5, transformer_prob=0.5)
        assert decide_severity(det, "host-1") == "info"

    def test_severity_is_in_closed_set(self):
        """Sanity: every branch returns one of the three contract values."""
        for tp, en in [(0.9, 0.9), (0.5, 0.9), (0.1, 0.1)]:
            det = _detection(transformer_prob=tp, ensemble=en)
            assert decide_severity(det, "h", critical_sources=frozenset({"h"})) in (
                "critical",
                "warning",
                "info",
            )


# -- Deduplicator -----------------------------------------------------------


class TestDeduplicator:
    def test_first_anomaly_starts_a_new_cluster(self):
        d = Deduplicator()
        cluster_id, size = d.assign("ERROR auth fail", "host-1", _now())
        assert cluster_id.startswith("clu_")
        assert size == 1

    def test_same_template_and_source_within_window_is_same_cluster(self):
        d = Deduplicator(window_s=60)
        t = _now()
        c1, n1 = d.assign("ERROR auth fail", "host-1", t)
        c2, n2 = d.assign("ERROR auth fail", "host-1", t + timedelta(seconds=30))
        assert c1 == c2
        assert n1 == 1 and n2 == 2

    def test_different_template_is_a_different_cluster(self):
        d = Deduplicator()
        t = _now()
        c1, _ = d.assign("ERROR auth fail", "host-1", t)
        c2, n = d.assign("ERROR connection refused", "host-1", t)
        assert c1 != c2
        assert n == 1

    def test_different_source_is_a_different_cluster(self):
        d = Deduplicator()
        t = _now()
        c1, _ = d.assign("ERROR auth fail", "host-1", t)
        c2, n = d.assign("ERROR auth fail", "host-2", t)
        assert c1 != c2
        assert n == 1

    def test_outside_window_starts_a_new_cluster(self):
        d = Deduplicator(window_s=60)
        t = _now()
        c1, _ = d.assign("ERROR auth fail", "host-1", t)
        c2, n = d.assign("ERROR auth fail", "host-1", t + timedelta(seconds=120))
        assert c1 != c2
        assert n == 1

    def test_invalid_window_raises(self):
        with pytest.raises(ValueError):
            Deduplicator(window_s=0)


# -- new_anomaly_id ---------------------------------------------------------


class TestNewAnomalyId:
    def test_format_matches_convention(self):
        ts = datetime(2026, 5, 1, 8, 19, 5, tzinfo=UTC)
        id_ = new_anomaly_id(ts)
        # `anom_<iso8601>_<4hex>` — see CLAUDE.md naming conventions
        assert id_.startswith("anom_2026-05-01T08:19:05_")
        assert len(id_.split("_")[-1]) == 4

    def test_uniqueness_for_same_timestamp(self):
        """4-hex suffix gives 16^4 = 65k addresses — birthday-paradox math
        says we expect a tiny but nonzero collision rate at N=50 (~1.8%).
        Assert "mostly unique" rather than "perfectly unique" so this isn't
        a flaky test."""
        ts = datetime(2026, 5, 1, 8, 19, 5, tzinfo=UTC)
        ids = {new_anomaly_id(ts) for _ in range(50)}
        assert len(ids) >= 45


# -- build_anomaly ----------------------------------------------------------


class TestBuildAnomaly:
    def test_returns_valid_pydantic_anomaly(self):
        window = build_windows(_events(20))[0]
        det = _detection(transformer_prob=0.4, ensemble=0.9, failure_min=12)
        ctx = AnomalyContext(
            window=window,
            detection=det,
            severity="warning",
            cluster_id="clu_xxxx",
            cluster_size=3,
        )
        a = build_anomaly(ctx)
        assert isinstance(a, Anomaly)
        assert a.severity == "warning"
        assert a.cluster_id == "clu_xxxx"
        assert a.cluster_size == 3
        assert a.source == window.source

    def test_critical_carries_predicted_failure_minutes(self):
        window = build_windows(_events(20))[0]
        det = _detection(transformer_prob=0.9, failure_min=8)
        ctx = AnomalyContext(
            window=window,
            detection=det,
            severity="critical",
            cluster_id="clu_x",
            cluster_size=1,
        )
        a = build_anomaly(ctx)
        assert a.predicted_failure_window_min == 8

    def test_non_critical_drops_predicted_failure_minutes(self):
        window = build_windows(_events(20))[0]
        det = _detection(failure_min=8)
        ctx = AnomalyContext(
            window=window,
            detection=det,
            severity="warning",
            cluster_id="clu_x",
            cluster_size=1,
        )
        assert build_anomaly(ctx).predicted_failure_window_min is None

    def test_top_contributing_lines_ranked_by_attention(self):
        window = build_windows(_events(20))[0]
        # Spike attention on indices 5 and 10 so they should rank top-2.
        attention = [0.0] * 20
        attention[5] = 0.7
        attention[10] = 0.2
        det = DetectionResult(
            ensemble_score=0.9,
            transformer_prob=0.5,
            ae_error_raw=0.0,
            ae_error_normalised=0.0,
            confidence=0.9,
            predicted_failure_minutes=0,
            attention=tuple(attention),
        )
        ctx = AnomalyContext(
            window=window,
            detection=det,
            severity="warning",
            cluster_id="clu_x",
            cluster_size=1,
        )
        a = build_anomaly(ctx)
        assert a.top_contributing_lines[0].line == window.raw_lines[5]
        assert a.top_contributing_lines[1].line == window.raw_lines[10]

    def test_clamps_out_of_range_scores_to_unit_interval(self):
        """Pydantic Field(ge=0, le=1) would 422; we silently clip rather
        than crash on a model that briefly produces 1.0001."""
        window = build_windows(_events(20))[0]
        det = DetectionResult(
            ensemble_score=1.05,
            transformer_prob=-0.01,
            ae_error_raw=0.0,
            ae_error_normalised=0.0,
            confidence=1.5,
            predicted_failure_minutes=0,
            attention=tuple([0.05] * 20),
        )
        ctx = AnomalyContext(
            window=window,
            detection=det,
            severity="info",
            cluster_id="clu_x",
            cluster_size=1,
        )
        a = build_anomaly(ctx)
        assert a.ensemble_score == 1.0
        assert a.failure_probability == 0.0
        assert a.confidence == 1.0


def _now() -> datetime:
    return datetime(2026, 5, 1, 9, 0, 0, tzinfo=UTC)
