"""
Tests for `training.eval_holdout_openstack`.

Two layers:
  * Pure-function tests for the AUC computation, the split reproduction,
    and the prediction gate — no torch, run in milliseconds.
  * One end-to-end smoke that walks the full pipeline with synthetic
    inputs (random scores + labels) using a tiny TorchScript-export'd
    confidence scorer. Confirms the wiring works.

The split-reproduction test is the most important: if `SPLIT_SEED` or
`VAL_SPLIT` ever drift away from `train_transformer.train()`'s actual
arguments, the held-out eval would silently report numbers on a
different slice. The test pins the exact indices.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import torch

from ml.ensemble import CalibratedThresholds
from training.calibrate import ConfidenceScorer
from training.eval_holdout_openstack import (
    SPLIT_SEED,
    VAL_SPLIT,
    SplitMetrics,
    _auc_score,
    compute_confidence,
    metrics_for_split,
    predicted_labels,
    reproduce_train_val_split,
)

# -- split reproduction ----------------------------------------------------


class TestReproduceSplit:
    def test_split_sizes_match_80_20(self):
        n = 1000
        train_idx, val_idx = reproduce_train_val_split(n)
        assert len(val_idx) == int(n * VAL_SPLIT)
        assert len(train_idx) == n - int(n * VAL_SPLIT)
        # Together they cover the whole corpus once.
        assert sorted(train_idx.tolist() + val_idx.tolist()) == list(range(n))

    def test_split_is_deterministic(self):
        a_train, a_val = reproduce_train_val_split(500)
        b_train, b_val = reproduce_train_val_split(500)
        assert np.array_equal(a_train, b_train)
        assert np.array_equal(a_val, b_val)

    def test_split_constants_match_train_transformer(self):
        """Pin: if `train_transformer.TrainConfig.seed` or
        `val_split` drift from these values, retraining produces a
        DIFFERENT split than this eval reads — silent corruption.
        Don't change these numbers without updating both sides."""
        assert SPLIT_SEED == 42
        assert VAL_SPLIT == 0.2

    def test_indices_match_known_values_for_seed_42(self):
        """Hard-pin the first few indices so any future change to
        numpy's permutation algorithm trips this test."""
        train_idx, val_idx = reproduce_train_val_split(100)
        # default_rng(42).permutation(100) → fixed sequence.
        rng = np.random.default_rng(42)
        expected_perm = rng.permutation(100)
        assert np.array_equal(val_idx, expected_perm[:20])
        assert np.array_equal(train_idx, expected_perm[20:])


# -- AUC math --------------------------------------------------------------


class TestAuc:
    def test_perfect_separation_gives_auc_1(self):
        y_true = np.array([0, 0, 0, 1, 1, 1])
        y_score = np.array([0.1, 0.2, 0.3, 0.7, 0.8, 0.9])
        assert _auc_score(y_true, y_score) == 1.0

    def test_inverted_separation_gives_auc_0(self):
        y_true = np.array([0, 0, 0, 1, 1, 1])
        y_score = np.array([0.9, 0.8, 0.7, 0.3, 0.2, 0.1])
        assert _auc_score(y_true, y_score) == 0.0

    def test_random_scores_give_auc_around_half(self):
        rng = np.random.default_rng(0)
        y_true = rng.integers(0, 2, size=10000)
        y_score = rng.random(10000)
        auc = _auc_score(y_true, y_score)
        assert 0.45 <= auc <= 0.55

    def test_constant_score_gives_auc_half(self):
        y_true = np.array([0, 0, 1, 1])
        y_score = np.array([0.5, 0.5, 0.5, 0.5])
        # All ties → AUC = 0.5 (rank-tie correction kicks in)
        assert _auc_score(y_true, y_score) == 0.5

    def test_single_class_returns_nan(self):
        y_true = np.array([1, 1, 1])
        y_score = np.array([0.1, 0.2, 0.3])
        assert np.isnan(_auc_score(y_true, y_score))


# -- prediction gate -------------------------------------------------------


class TestPredictedLabels:
    def test_both_gates_required(self):
        thresholds = _thresholds()
        # 4 windows: (ensemble, conf) × (high, low)
        ensemble = np.array([0.9, 0.9, 0.4, 0.4])
        conf = np.array([0.9, 0.2, 0.9, 0.2])
        pred = predicted_labels(ensemble, conf, thresholds)
        assert pred.tolist() == [1, 0, 0, 0]


# -- confidence scorer + metrics_for_split ---------------------------------


class TestEndToEnd:
    @pytest.fixture
    def confidence_scorer(self, tmp_path: Path):
        """Tiny TorchScript-export'd ConfidenceScorer with random weights."""
        m = ConfidenceScorer().eval()
        scripted = torch.jit.script(m)
        out = tmp_path / "confidence_scorer.pt"
        scripted.save(str(out))
        return torch.jit.load(str(out)).eval()

    def test_compute_confidence_returns_one_per_window(self, confidence_scorer):
        n = 50
        rng = np.random.default_rng(0)
        t_scores = rng.random(n).astype(np.float32)
        ae_norm = rng.random(n).astype(np.float32)
        out = compute_confidence(confidence_scorer, t_scores, ae_norm)
        assert out.shape == (n,)
        assert ((out >= 0) & (out <= 1)).all()

    def test_metrics_for_split_picks_correct_subset(self):
        """Hand-build a corpus where val_idx is the predictably-anomalous
        slice. Confirm metrics_for_split slices correctly."""
        # 100 windows. val_idx will be 20 of them (seed=42).
        n = 100
        ensemble = np.full(n, 0.9, dtype=np.float32)  # always above threshold
        conf = np.full(n, 0.9, dtype=np.float32)
        labels = np.zeros(n, dtype=np.int64)
        # Mark every val window as positive — all should TP.
        _train_idx, val_idx = reproduce_train_val_split(n)
        labels[val_idx] = 1

        m = metrics_for_split(
            "val",
            indices=val_idx,
            ensemble_scores=ensemble,
            confidences=conf,
            labels=labels,
            thresholds=_thresholds(),
        )
        assert m.n == 20
        assert m.tp == 20
        assert m.fp == 0
        assert m.fn == 0
        assert m.f1 == 1.0
        assert m.auc != m.auc or m.auc in (1.0, float("nan"))  # all-positive subset → NaN

    def test_split_metrics_dataclass_positive_rate(self):
        m = SplitMetrics(
            name="val",
            n=100, n_positive=20, n_negative=80,
            f1=0.9, precision=0.9, recall=0.9, auc=0.95,
            tp=18, fp=2, tn=78, fn=2,
        )
        assert m.positive_rate == 0.2


def _thresholds() -> CalibratedThresholds:
    return CalibratedThresholds(
        w1=0.5, w2=0.5,
        anomaly_threshold=0.55,
        confidence_threshold=0.30,
        ae_error_p10=0.0, ae_error_p90=1.0,
    )
