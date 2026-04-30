"""
Tests for ml/ensemble.py — the score combiner used by both calibration
and the live detector.
"""
import json
from pathlib import Path

import numpy as np
import pytest

from ml.ensemble import (
    CalibratedThresholds,
    combine,
    normalise_ae_error,
)


class TestNormaliseAeError:
    def test_clips_to_unit_interval(self):
        errors = np.array([-1.0, 0.0, 0.5, 1.0, 5.0])
        out = normalise_ae_error(errors, p10=0.0, p90=1.0)
        assert out.min() >= 0.0 and out.max() <= 1.0

    def test_p10_maps_to_zero(self):
        errors = np.array([0.1, 0.5, 0.9])
        out = normalise_ae_error(errors, p10=0.1, p90=0.9)
        assert out[0] == pytest.approx(0.0)

    def test_p90_maps_to_one(self):
        errors = np.array([0.1, 0.5, 0.9])
        out = normalise_ae_error(errors, p10=0.1, p90=0.9)
        assert out[-1] == pytest.approx(1.0)

    def test_handles_degenerate_p10_equals_p90(self):
        """When all errors are identical, normalisation must not divide by zero."""
        errors = np.full(5, 0.5)
        out = normalise_ae_error(errors, p10=0.5, p90=0.5)
        assert out.shape == errors.shape  # doesn't crash


class TestCombine:
    def _thresholds(self) -> CalibratedThresholds:
        return CalibratedThresholds(
            w1=0.6, w2=0.4,
            anomaly_threshold=0.5, confidence_threshold=0.65,
            ae_error_p10=0.0, ae_error_p90=1.0,
        )

    def test_weighted_sum(self):
        t = self._thresholds()
        probs = np.array([0.0, 1.0])
        errs = np.array([0.0, 1.0])
        out = combine(probs, errs, thresholds=t)
        assert out[0] == pytest.approx(0.0)
        assert out[1] == pytest.approx(1.0)

    def test_weights_sum_to_one_for_extremes(self):
        t = self._thresholds()
        probs = np.array([1.0])
        errs = np.array([1.0])
        out = combine(probs, errs, thresholds=t)
        # 0.6*1 + 0.4*1 = 1.0
        assert out[0] == pytest.approx(1.0)

    def test_shape_mismatch_rejected(self):
        t = self._thresholds()
        with pytest.raises(ValueError, match=r"shape mismatch"):
            combine(np.zeros(5), np.zeros(4), thresholds=t)


class TestSaveLoad:
    def test_round_trip(self, tmp_path: Path):
        original = CalibratedThresholds(
            w1=0.62, w2=0.38,
            anomaly_threshold=0.71, confidence_threshold=0.65,
            ae_error_p10=0.001, ae_error_p90=0.123,
        )
        dest = tmp_path / "thresholds.json"
        original.save(dest)
        loaded = CalibratedThresholds.load(dest)
        assert loaded == original

    def test_save_writes_json_with_expected_keys(self, tmp_path: Path):
        t = CalibratedThresholds(
            w1=0.5, w2=0.5,
            anomaly_threshold=0.5, confidence_threshold=0.5,
            ae_error_p10=0.0, ae_error_p90=1.0,
        )
        dest = tmp_path / "thresholds.json"
        t.save(dest)
        payload = json.loads(dest.read_text())
        assert set(payload.keys()) == {
            "w1", "w2", "anomaly_threshold", "confidence_threshold",
            "ae_error_p10", "ae_error_p90",
        }
