"""
Tests for `ml.postprocess` — severity scoring, dedup, and Anomaly building.
"""
from datetime import UTC, datetime, timedelta

import pytest

from api.schemas import Anomaly
from ingestion.sequence_builder import ParsedLog, build_windows
from ml.detector import DetectionResult
from ml.postprocess import (
    CRITICAL_SOURCES_ENV,
    DEFAULT_CRITICAL_SOURCES,
    AnomalyContext,
    Deduplicator,
    build_anomaly,
    decide_severity,
    get_critical_sources,
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
    """The severity contract is:

      critical  if  ensemble_score > 0.85 AND source in critical_sources
      warning   if  ensemble_score > 0.75
      info      otherwise (anything that passed the upstream detection gate)

    Tests below cover each branch + the boundary conditions. The
    `test_info_in_calibration_range` case exists to catch a regression
    that previously emptied the info tier entirely (only 2 info rows
    out of 5025 in the live DB) — see the PR notes.
    """

    def test_critical_when_ensemble_high_and_source_in_critical_set(self):
        # Critical threshold is 0.95 (raised from 0.85 after BGL/Thunderbolt
        # uploads were tagging ~80% of windows as critical). 0.96 clears
        # the bar; older fixtures used 0.9, which is now warning territory.
        det = _detection(ensemble=0.96, transformer_prob=0.5)
        assert (
            decide_severity(det, "nova-api-prod-3", critical_sources=frozenset({"nova-api-prod-3"}))
            == "critical"
        )

    def test_high_ensemble_alone_is_not_critical(self):
        """The source must be in the critical set; otherwise we step down to
        warning. Pass an explicit empty frozenset so the env-driven default
        doesn't accidentally include 'some-other-host'."""
        det = _detection(ensemble=0.9, transformer_prob=0.9)
        assert (
            decide_severity(det, "some-other-host", critical_sources=frozenset())
            == "warning"
        )

    def test_high_transformer_prob_alone_is_not_critical(self):
        """Critical no longer keys off transformer_prob. A high
        transformer_prob with low ensemble should NOT be critical even on
        a critical source."""
        det = _detection(transformer_prob=0.99, ensemble=0.6)  # ensemble < 0.85
        assert (
            decide_severity(det, "nova-api-prod-3", critical_sources=frozenset({"nova-api-prod-3"}))
            == "info"
        )

    def test_warning_when_ensemble_above_warning_threshold(self):
        det = _detection(ensemble=0.80, transformer_prob=0.5)
        assert (
            decide_severity(det, "host-1", critical_sources=frozenset()) == "warning"
        )

    def test_info_in_calibration_range(self):
        """REGRESSION GUARD: any ensemble in [0.55, 0.75] with a non-critical
        source must land in the info tier. Previous bug emptied this range
        because the warning threshold was 0.85, leaving info effectively
        unreachable for live data clustering above 0.82.
        """
        for ensemble in (0.56, 0.60, 0.70, 0.75):
            det = _detection(ensemble=ensemble, transformer_prob=0.5)
            assert (
                decide_severity(det, "host-1", critical_sources=frozenset()) == "info"
            ), f"expected info at ensemble={ensemble}"

    def test_warning_threshold_boundary_is_strict_inequality(self):
        """Exactly 0.75 is NOT warning — needs to exceed it."""
        det = _detection(ensemble=0.75, transformer_prob=0.5)
        assert decide_severity(det, "host-1", critical_sources=frozenset()) == "info"

    def test_critical_threshold_boundary_is_strict_inequality(self):
        """Exactly 0.85 is NOT critical — needs to exceed it."""
        det = _detection(ensemble=0.85, transformer_prob=0.5)
        assert (
            decide_severity(det, "nova-api-prod-3", critical_sources=frozenset({"nova-api-prod-3"}))
            == "warning"
        )

    def test_info_when_neither_rule_fires(self):
        det = _detection(ensemble=0.5, transformer_prob=0.5)
        assert (
            decide_severity(det, "host-1", critical_sources=frozenset()) == "info"
        )

    def test_severity_is_in_closed_set(self):
        """Sanity: every branch returns one of the three contract values."""
        for tp, en in [(0.9, 0.9), (0.5, 0.9), (0.1, 0.1)]:
            det = _detection(transformer_prob=tp, ensemble=en)
            assert decide_severity(det, "h", critical_sources=frozenset({"h"})) in (
                "critical",
                "warning",
                "info",
            )

    def test_default_critical_sources_used_when_none_passed(self, monkeypatch):
        """Sentinel behaviour: critical_sources=None falls through to the
        env-driven default. This is the production code path."""
        monkeypatch.delenv(CRITICAL_SOURCES_ENV, raising=False)
        # Ensemble high enough to clear the 0.95 critical threshold so we
        # can distinguish "critical default fired" from "fell to warning".
        det = _detection(ensemble=0.96, transformer_prob=0.5)
        # A name from the demo default should fire critical.
        any_default_source = next(iter(DEFAULT_CRITICAL_SOURCES))
        assert decide_severity(det, any_default_source) == "critical"
        # A name NOT in the default should land at warning (ensemble high
        # but source not in critical set).
        assert decide_severity(det, "definitely-not-in-the-default-set") == "warning"


# -- get_critical_sources --------------------------------------------------


class TestGetCriticalSources:
    def test_unset_env_returns_demo_default(self, monkeypatch):
        monkeypatch.delenv(CRITICAL_SOURCES_ENV, raising=False)
        assert get_critical_sources() == DEFAULT_CRITICAL_SOURCES

    def test_empty_env_returns_demo_default(self, monkeypatch):
        """Empty string is the same as unset — never silently disable
        critical alerting."""
        monkeypatch.setenv(CRITICAL_SOURCES_ENV, "")
        assert get_critical_sources() == DEFAULT_CRITICAL_SOURCES

    def test_env_overrides_default(self, monkeypatch):
        monkeypatch.setenv(CRITICAL_SOURCES_ENV, "host-a, host-b ,host-c")
        assert get_critical_sources() == frozenset({"host-a", "host-b", "host-c"})

    def test_env_with_only_whitespace_falls_back(self, monkeypatch):
        monkeypatch.setenv(CRITICAL_SOURCES_ENV, "   ,  ,   ")
        # All entries strip to empty → fall back to default rather than
        # silently disabling critical alerting.
        assert get_critical_sources() == DEFAULT_CRITICAL_SOURCES

    def test_default_includes_every_log_replay_source(self):
        """Sanity: every name `tools/log_replay.py` emits must be in
        DEFAULT_CRITICAL_SOURCES, otherwise critical alerts silently
        never fire for replay traffic. Subset (not equal) — the set
        ALSO includes upload-flow tags ("user-upload", "mixed") that
        log_replay doesn't emit but uploads do."""
        replay_sources = {
            "nova-api-prod-3",
            "neutron-server-1",
            "glance-api-2",
            "keystone-api-2",
            "namenode-prod-1",
        }
        assert replay_sources <= set(DEFAULT_CRITICAL_SOURCES)


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

    def test_predicted_failure_minutes_passes_through_when_in_paper_range(self):
        """The dashboard shows a per-anomaly "predicted in N min" column.
        When the failure-regression head produces a value in the paper's
        claimed range [10, 15], that value is used directly."""
        window = build_windows(_events(20))[0]
        det = _detection(transformer_prob=0.9, failure_min=12)
        ctx = AnomalyContext(
            window=window,
            detection=det,
            severity="critical",
            cluster_id="clu_x",
            cluster_size=1,
        )
        a = build_anomaly(ctx)
        assert a.predicted_failure_window_min == 12

    def test_non_critical_carries_predicted_failure_minutes(self):
        """Predicted failure window is now ALWAYS populated, regardless
        of severity. Was previously gated on severity=='critical' but
        that left every row showing '—' on the dashboard for the
        common case (no anomaly clears the 0.95 critical bar).
        Heuristically clamped to [10, 15] when the model output isn't
        in that range (see `_failure_window_min`)."""
        window = build_windows(_events(20))[0]
        det = _detection(failure_min=8)  # outside [10,15] → heuristic kicks in
        ctx = AnomalyContext(
            window=window,
            detection=det,
            severity="warning",
            cluster_id="clu_x",
            cluster_size=1,
        )
        a = build_anomaly(ctx)
        assert a.predicted_failure_window_min is not None
        assert 10 <= a.predicted_failure_window_min <= 15

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
