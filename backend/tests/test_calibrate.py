"""
Tests for training/calibrate.py — grid search + confidence MLP.

Synthetic data: transformer scores correlate strongly with labels (the
transformer would be doing its job in real life), AE errors weakly correlate.
The grid search should pick a w1 favouring the transformer.
"""
import json
from pathlib import Path

import numpy as np
import pytest
import torch

from ml.ensemble import CalibratedThresholds
from training.calibrate import (
    ConfidenceScorer,
    GridSearchResult,
    build_confidence_features,
    calibrate,
    grid_search,
    pick_confidence_threshold,
    save_confidence_torchscript,
    train_confidence_scorer,
)


def _synth_scores(n: int = 200, seed: int = 17):
    """Transformer score is a noisy version of the label; AE is weakly correlated."""
    rng = np.random.default_rng(seed)
    labels = rng.binomial(1, 0.3, size=n).astype(np.float32)
    transformer_scores = np.clip(labels + rng.normal(0, 0.2, size=n), 0.0, 1.0).astype(np.float32)
    ae_errors = np.clip(0.3 * labels + rng.normal(0, 0.3, size=n), 0.0, 2.0).astype(np.float32)
    return transformer_scores, ae_errors, labels


# -- grid_search ----------------------------------------------------------

class TestGridSearch:
    def test_returns_well_formed_result(self):
        t, e, lbl = _synth_scores()
        # Pre-normalise the AE errors here — grid_search expects [0,1] inputs.
        e_norm = np.clip(e / np.percentile(e, 90), 0, 1).astype(np.float32)
        result = grid_search(t, e_norm, lbl)
        assert isinstance(result, GridSearchResult)
        assert 0.0 <= result.f1 <= 1.0
        assert 0.3 <= result.w1 <= 0.9
        assert 0.3 <= result.anomaly_threshold <= 0.9
        assert result.w1 + result.w2 == pytest.approx(1.0)

    def test_finds_better_than_random(self):
        t, e, lbl = _synth_scores()
        e_norm = np.clip(e / np.percentile(e, 90), 0, 1).astype(np.float32)
        result = grid_search(t, e_norm, lbl)
        # Better than coin-flip on a learnable problem
        assert result.f1 > 0.5

    def test_rejects_shape_mismatch(self):
        with pytest.raises(ValueError):
            grid_search(np.zeros(5), np.zeros(4), np.zeros(5))


# -- ConfidenceScorer -----------------------------------------------------

class TestConfidenceScorer:
    def test_forward_shape(self):
        m = ConfidenceScorer()
        x = torch.randn(4, 4)
        assert m(x).shape == (4, 1)

    def test_torchscript_scriptable(self, tmp_path: Path):
        m = ConfidenceScorer().eval()
        scripted = torch.jit.script(m)
        x = torch.randn(2, 4)
        with torch.no_grad():
            assert torch.allclose(m(x), scripted(x), atol=1e-5)

    def test_save_creates_file(self, tmp_path: Path):
        m = ConfidenceScorer()
        dest = tmp_path / "confidence.pt"
        save_confidence_torchscript(m, dest)
        assert dest.exists()
        loaded = torch.jit.load(str(dest))
        x = torch.randn(2, 4)
        m.eval()
        with torch.no_grad():
            assert torch.allclose(m(x), loaded(x), atol=1e-5)


# -- build_confidence_features --------------------------------------------

class TestBuildFeatures:
    def test_returns_4_columns(self):
        n = 10
        t = np.zeros(n, dtype=np.float32)
        e = np.zeros(n, dtype=np.float32)
        feat = build_confidence_features(t, e)
        assert feat.shape == (n, 4)

    def test_unprovided_features_default_to_zero(self):
        t = np.array([0.5], dtype=np.float32)
        e = np.array([0.7], dtype=np.float32)
        feat = build_confidence_features(t, e)
        assert feat[0, 2] == 0.0  # seq_len_norm
        assert feat[0, 3] == 0.0  # time_of_day_norm


# -- train_confidence_scorer ----------------------------------------------

class TestTrainConfidenceScorer:
    def test_training_runs(self):
        rng = np.random.default_rng(0)
        n = 100
        features = rng.uniform(0, 1, size=(n, 4)).astype(np.float32)
        targets = rng.binomial(1, 0.6, size=n).astype(np.float32)
        model, metrics = train_confidence_scorer(features, targets, epochs=3, verbose=False)
        assert isinstance(model, ConfidenceScorer)
        assert "best_val_loss" in metrics
        assert "history" in metrics
        assert len(metrics["history"]) == 3

    def test_pick_threshold_returns_in_range(self):
        rng = np.random.default_rng(0)
        n = 80
        features = rng.uniform(0, 1, size=(n, 4)).astype(np.float32)
        targets = rng.binomial(1, 0.5, size=n).astype(np.float32)
        model, _ = train_confidence_scorer(features, targets, epochs=3, verbose=False)
        threshold = pick_confidence_threshold(model, features, targets)
        assert 0.3 <= threshold <= 0.9


# -- end-to-end calibrate() -----------------------------------------------

class TestCalibrate:
    def test_writes_thresholds_and_confidence(self, tmp_path: Path):
        t, e, lbl = _synth_scores()
        thresh_path = tmp_path / "thresholds.json"
        conf_path = tmp_path / "confidence.pt"
        metrics = calibrate(
            t, e, lbl,
            thresholds_out=thresh_path,
            confidence_out=conf_path,
            verbose=False,
        )
        assert thresh_path.exists()
        assert conf_path.exists()
        # Returned metrics dict has the expected sections
        assert "ensemble" in metrics
        assert "confidence" in metrics
        assert "w1" in metrics["ensemble"]
        assert "ae_error_p10" in metrics["ensemble"]
        assert "ae_error_p90" in metrics["ensemble"]

    def test_thresholds_loadable_via_ensemble_module(self, tmp_path: Path):
        """The file calibrate.py writes must round-trip through
        ml.ensemble.CalibratedThresholds — that's the contract with the
        live detector."""
        t, e, lbl = _synth_scores()
        thresh_path = tmp_path / "thresholds.json"
        conf_path = tmp_path / "confidence.pt"
        calibrate(
            t, e, lbl,
            thresholds_out=thresh_path, confidence_out=conf_path,
            verbose=False,
        )
        loaded = CalibratedThresholds.load(thresh_path)
        assert 0.0 <= loaded.w1 <= 1.0
        assert 0.0 <= loaded.w2 <= 1.0
        assert loaded.w1 + loaded.w2 == pytest.approx(1.0)
        assert 0.0 <= loaded.anomaly_threshold <= 1.0
        assert 0.0 <= loaded.confidence_threshold <= 1.0

    def test_thresholds_json_has_all_required_fields(self, tmp_path: Path):
        t, e, lbl = _synth_scores()
        thresh_path = tmp_path / "thresholds.json"
        conf_path = tmp_path / "confidence.pt"
        calibrate(t, e, lbl, thresholds_out=thresh_path, confidence_out=conf_path, verbose=False)
        payload = json.loads(thresh_path.read_text())
        assert set(payload) == {
            "w1", "w2", "anomaly_threshold", "confidence_threshold",
            "ae_error_p10", "ae_error_p90",
        }
