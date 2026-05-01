"""
Tests for `training.eval_cross_dataset`.

Two layers:
  * Pure-function tests for the level-based labeller and the
    confusion-matrix math — no torch / SBERT, run in milliseconds.
  * One end-to-end smoke that walks the full pipeline against a tiny
    inline Apache fixture using a stub embedder + a freshly-jit'd
    detector. Verifies the wiring without pulling sentence-transformers.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import torch

from ml.autoencoder import LogAutoEncoder
from ml.detector import (
    ARTIFACT_AUTOENCODER,
    ARTIFACT_CONFIDENCE,
    ARTIFACT_THRESHOLDS,
    ARTIFACT_TRANSFORMER,
    Detector,
)
from ml.ensemble import CalibratedThresholds
from ml.transformer import LogTransformer
from training.calibrate import ConfidenceScorer
from training.eval_cross_dataset import (
    LEVEL_RE,
    confusion,
    label_windows,
    make_level_labeler,
    parse_apache,
    predict_anomalies,
)
from training.sequence_builder import WINDOW_SIZE, ParsedLog, build_windows

# -- level-based labeller --------------------------------------------------


class TestLevelLabeller:
    def test_error_token_marks_window_anomaly(self):
        labeler = make_level_labeler()
        events = _events_with_levels(["[notice]"] * 19 + ["[error]"])
        assert labeler(events) == "anomaly"

    def test_warn_token_marks_window_anomaly(self):
        labeler = make_level_labeler()
        events = _events_with_levels(["[notice]"] * 19 + ["[warn]"])
        assert labeler(events) == "anomaly"

    def test_fatal_token_marks_window_anomaly(self):
        labeler = make_level_labeler()
        events = _events_with_levels(["[notice]"] * 19 + ["[fatal]"])
        assert labeler(events) == "anomaly"

    def test_notice_only_window_is_normal(self):
        labeler = make_level_labeler()
        events = _events_with_levels(["[notice]"] * 20)
        assert labeler(events) == "normal"

    def test_level_match_is_case_insensitive(self):
        labeler = make_level_labeler()
        events = _events_with_levels(["[notice]"] * 19 + ["[ERROR]"])
        assert labeler(events) == "anomaly"

    def test_level_re_does_not_match_inside_other_words(self):
        """The pattern requires bracketed levels — `errorred` shouldn't trip it."""
        assert LEVEL_RE.search("errorred something") is None
        assert LEVEL_RE.search("[error] real apache prefix") is not None


# -- confusion matrix math -------------------------------------------------


class TestConfusion:
    def test_perfect_classifier(self):
        pred = np.array([1, 1, 0, 0])
        truth = np.array([1, 1, 0, 0])
        r = confusion(pred, truth)
        assert r.tp == 2
        assert r.fp == 0
        assert r.tn == 2
        assert r.fn == 0
        assert r.precision == 1.0
        assert r.recall == 1.0
        assert r.f1 == 1.0
        assert r.accuracy == 1.0

    def test_all_negative_classifier(self):
        pred = np.array([0, 0, 0, 0])
        truth = np.array([1, 1, 0, 0])
        r = confusion(pred, truth)
        assert r.tp == 0
        assert r.fp == 0
        assert r.tn == 2
        assert r.fn == 2
        assert r.precision == 0.0
        assert r.recall == 0.0
        assert r.f1 == 0.0

    def test_balanced_mixed_results(self):
        pred = np.array([1, 0, 1, 0])
        truth = np.array([1, 1, 0, 0])
        r = confusion(pred, truth)
        assert (r.tp, r.fp, r.tn, r.fn) == (1, 1, 1, 1)
        assert r.precision == 0.5
        assert r.recall == 0.5
        assert r.f1 == pytest.approx(0.5)

    def test_positive_rate_field(self):
        truth = np.array([1, 1, 1, 0, 0, 0, 0, 0, 0, 0])  # 30% positive
        r = confusion(np.zeros_like(truth), truth)
        assert r.positive_rate == pytest.approx(0.3)


# -- end-to-end (no SBERT) -------------------------------------------------


@pytest.fixture
def tiny_artifacts(tmp_path: Path) -> Path:
    """Tiny TorchScript detector + thresholds saved to a tmp dir."""
    torch.jit.script(LogTransformer().eval()).save(
        str(tmp_path / ARTIFACT_TRANSFORMER)
    )
    torch.jit.script(LogAutoEncoder().eval()).save(
        str(tmp_path / ARTIFACT_AUTOENCODER)
    )
    torch.jit.script(ConfidenceScorer().eval()).save(
        str(tmp_path / ARTIFACT_CONFIDENCE)
    )
    CalibratedThresholds(
        w1=0.5, w2=0.5,
        anomaly_threshold=0.55,
        confidence_threshold=0.3,
        ae_error_p10=0.0, ae_error_p90=1.0,
    ).save(tmp_path / ARTIFACT_THRESHOLDS)
    return tmp_path


def test_predict_anomalies_returns_bool_array(tiny_artifacts: Path):
    """Smoke-test that `predict_anomalies` returns one bool per window
    and never crashes on a small batch."""
    detector = Detector.from_artifacts(tiny_artifacts)
    rng = np.random.default_rng(0)
    embeddings = rng.standard_normal((4, WINDOW_SIZE, 384)).astype(np.float32)
    out = predict_anomalies(detector, embeddings)
    assert out.shape == (4,)
    assert out.dtype == bool


def test_predict_anomalies_rejects_2d_input(tiny_artifacts: Path):
    detector = Detector.from_artifacts(tiny_artifacts)
    with pytest.raises(ValueError, match="expected"):
        predict_anomalies(detector, np.zeros((20, 384), dtype=np.float32))


def test_label_windows_returns_per_window_truth():
    """Build a few windows with known anomaly content and confirm the
    bool array matches."""
    # Window 0: all notice → normal
    notice = _events_with_levels(["[notice]"] * 20)
    # Window 1: contains error → anomaly
    erring = _events_with_levels(["[notice]"] * 19 + ["[error]"])

    # Build batch: prepend offset to fake distinct line_no's so windows
    # don't get mixed.
    for i, e in enumerate(notice):
        e.line_no = i
    for i, e in enumerate(erring):
        e.line_no = i + 100

    labeler = make_level_labeler()
    windows_a = build_windows(notice, label_fn=labeler)
    windows_b = build_windows(erring, label_fn=labeler)

    all_windows = windows_a + windows_b
    truth = label_windows(all_windows)
    assert truth.tolist() == [False, True]


def test_parse_apache_uses_separate_drain3_state(tmp_path: Path):
    """Calling parse_apache must not mutate any pre-existing drain3
    state — the production state file lives at a different path."""
    apache_log = tmp_path / "apache.log"
    apache_log.write_text(
        "\n".join(
            f"[Sat Jun 24 14:40:0{i % 10} 2005] [notice] worker started {i}"
            for i in range(30)
        ),
        encoding="utf-8",
    )
    eval_state = tmp_path / "eval_state.bin"
    parsed = parse_apache(apache_log, drain3_state_out=eval_state, sample=None)

    assert eval_state.exists(), "eval state file should be written"
    assert len(parsed) == 30
    # All ParsedLogs should be tagged with the eval source label.
    assert {p.source for p in parsed} == {"apache"}


# -- helpers ---------------------------------------------------------------


def _events_with_levels(level_tokens: list[str]) -> list[ParsedLog]:
    """Build 20 ParsedLog records with a level token in each raw line."""
    return [
        ParsedLog(
            raw=f"[Sat Jun 24 14:40:00 2005] {tok} synthetic line {i}",
            template=f"[<*>] {tok} synthetic line <*>",
            template_id=str(i),
            source="apache",
            line_no=i,
        )
        for i, tok in enumerate(level_tokens)
    ]
