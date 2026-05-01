"""
Tests for `ml.detector.Detector`.

Strategy: build small `LogTransformer` / `LogAutoEncoder` / `ConfidenceScorer`
modules with fresh random weights, TorchScript-export them to a tmpdir,
write a thresholds.json alongside, then load via `Detector.from_artifacts`
and assert the output shape + value ranges. We don't validate actual
detection accuracy here — that's the training pipeline's job.
"""
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
    DetectionResult,
    Detector,
)
from ml.ensemble import CalibratedThresholds
from ml.transformer import SBERT_DIM, WINDOW_LEN, LogTransformer
from training.calibrate import ConfidenceScorer


@pytest.fixture
def artifact_dir(tmp_path: Path) -> Path:
    """Build + jit + save a tiny detector to disk and return the artifact dir."""
    transformer = LogTransformer().eval()
    autoencoder = LogAutoEncoder().eval()
    confidence = ConfidenceScorer().eval()

    torch.jit.script(transformer).save(str(tmp_path / ARTIFACT_TRANSFORMER))
    torch.jit.script(autoencoder).save(str(tmp_path / ARTIFACT_AUTOENCODER))
    torch.jit.script(confidence).save(str(tmp_path / ARTIFACT_CONFIDENCE))

    thresholds = CalibratedThresholds(
        w1=0.5,
        w2=0.5,
        anomaly_threshold=0.55,
        confidence_threshold=0.3,
        ae_error_p10=0.0,
        ae_error_p90=1.0,
    )
    thresholds.save(tmp_path / ARTIFACT_THRESHOLDS)
    return tmp_path


def _embedding(seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return rng.standard_normal((WINDOW_LEN, SBERT_DIM)).astype(np.float32)


def test_from_artifacts_loads_all_four_files(artifact_dir: Path):
    detector = Detector.from_artifacts(artifact_dir)
    assert detector.thresholds.w1 == 0.5


def test_from_artifacts_missing_file_raises(tmp_path: Path):
    # Empty dir
    with pytest.raises(FileNotFoundError):
        Detector.from_artifacts(tmp_path)


def test_score_returns_valid_detection_result(artifact_dir: Path):
    detector = Detector.from_artifacts(artifact_dir)
    result = detector.score(_embedding(seed=0))

    assert isinstance(result, DetectionResult)
    # All scores in [0, 1] (sigmoids + ensemble combine on clipped AE error).
    assert 0.0 <= result.transformer_prob <= 1.0
    assert 0.0 <= result.confidence <= 1.0
    assert 0.0 <= result.ensemble_score <= 1.0
    assert 0.0 <= result.ae_error_normalised <= 1.0
    assert result.ae_error_raw >= 0.0
    # Failure-minutes is non-negative integer (clamped).
    assert isinstance(result.predicted_failure_minutes, int)
    assert result.predicted_failure_minutes >= 0
    # Attention is one float per event in the window, ≈ sums to 1.
    assert len(result.attention) == WINDOW_LEN
    assert sum(result.attention) == pytest.approx(1.0, abs=1e-3)


def test_score_is_deterministic_for_same_input(artifact_dir: Path):
    detector = Detector.from_artifacts(artifact_dir)
    emb = _embedding(seed=42)
    a = detector.score(emb)
    b = detector.score(emb)
    assert a == b


def test_score_rejects_wrong_input_shape(artifact_dir: Path):
    detector = Detector.from_artifacts(artifact_dir)
    with pytest.raises(ValueError, match="2-D embedding"):
        detector.score(np.zeros(SBERT_DIM, dtype=np.float32))  # 1-D
    with pytest.raises(Exception):  # noqa: B017 — torch raises its own type
        detector.score(np.zeros((WINDOW_LEN, SBERT_DIM - 1), dtype=np.float32))


def test_is_anomaly_applies_both_gates(artifact_dir: Path):
    detector = Detector.from_artifacts(artifact_dir)
    # Synthesise: high score + high confidence → anomaly
    high = DetectionResult(
        ensemble_score=0.9,
        transformer_prob=0.9,
        ae_error_raw=0.1,
        ae_error_normalised=0.1,
        confidence=0.9,
        predicted_failure_minutes=5,
        attention=tuple([0.05] * WINDOW_LEN),
    )
    assert detector.is_anomaly(high)

    # Below ensemble threshold
    low_score = DetectionResult(
        ensemble_score=0.1,
        transformer_prob=0.1,
        ae_error_raw=0.0,
        ae_error_normalised=0.0,
        confidence=0.9,
        predicted_failure_minutes=0,
        attention=tuple([0.05] * WINDOW_LEN),
    )
    assert not detector.is_anomaly(low_score)

    # High score but low confidence — confidence gate blocks it
    low_conf = DetectionResult(
        ensemble_score=0.9,
        transformer_prob=0.9,
        ae_error_raw=0.1,
        ae_error_normalised=0.1,
        confidence=0.1,
        predicted_failure_minutes=5,
        attention=tuple([0.05] * WINDOW_LEN),
    )
    assert not detector.is_anomaly(low_conf)
