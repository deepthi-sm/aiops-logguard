"""
Ensemble combiner — turns the Transformer's anomaly probability and the
AutoEncoder's reconstruction error into a single calibrated score per window.

Per docs/architecture/system_overview.md (Layer 4b):

    combined_score = w1 * transformer_prob + w2 * normalize(ae_error)

The Transformer captures sequence-level patterns; the AE captures
distributional drift. They fail in different ways, so the combined score
is more robust than either alone.

Live detector (Step 4) uses the same `Ensemble` class loaded from the
calibrated `artifacts/thresholds.json` — there's a single code path between
training-time evaluation and inference.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np


@dataclass(frozen=True)
class CalibratedThresholds:
    """The numbers calibration writes to `artifacts/thresholds.json`."""
    w1: float
    w2: float
    anomaly_threshold: float
    confidence_threshold: float
    # Percentile-based AE error normalisation params (fit on the val set so
    # we don't get tail-dragged by training-time outliers).
    ae_error_p10: float
    ae_error_p90: float

    def to_dict(self) -> dict:
        return {
            "w1": float(self.w1),
            "w2": float(self.w2),
            "anomaly_threshold": float(self.anomaly_threshold),
            "confidence_threshold": float(self.confidence_threshold),
            "ae_error_p10": float(self.ae_error_p10),
            "ae_error_p90": float(self.ae_error_p90),
        }

    def save(self, dest: Path) -> None:
        dest.parent.mkdir(parents=True, exist_ok=True)
        with dest.open("w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2)

    @classmethod
    def load(cls, src: Path) -> CalibratedThresholds:
        with src.open("r", encoding="utf-8") as f:
            d = json.load(f)
        return cls(
            w1=float(d["w1"]),
            w2=float(d["w2"]),
            anomaly_threshold=float(d["anomaly_threshold"]),
            confidence_threshold=float(d["confidence_threshold"]),
            ae_error_p10=float(d["ae_error_p10"]),
            ae_error_p90=float(d["ae_error_p90"]),
        )


def normalise_ae_error(
    errors: np.ndarray, *, p10: float, p90: float,
) -> np.ndarray:
    """Map AE reconstruction error into [0, 1] using percentile clip-and-scale.

    Linearly maps `[p10, p90] → [0, 1]`, clipping below/above. Robust to
    training-time outliers because we use percentiles rather than min/max.
    """
    span = max(p90 - p10, 1e-9)
    scaled = (errors - p10) / span
    return np.clip(scaled, 0.0, 1.0)


def combine(
    transformer_probs: np.ndarray,
    ae_errors: np.ndarray,
    *,
    thresholds: CalibratedThresholds,
) -> np.ndarray:
    """Combine the two component scores into the final ensemble score.

    Args:
        transformer_probs: (N,) — sigmoid output of `transformer.anomaly_logit`.
        ae_errors:         (N,) — output of `autoencoder.reconstruction_error`.
        thresholds:        the calibrated weights + percentile params.

    Returns: (N,) ensemble scores in [0, 1]. Apply `thresholds.anomaly_threshold`
    to get the binary anomaly decision.
    """
    if transformer_probs.shape != ae_errors.shape:
        raise ValueError(
            f"shape mismatch: transformer {transformer_probs.shape} vs "
            f"ae {ae_errors.shape}"
        )
    norm_ae = normalise_ae_error(
        ae_errors, p10=thresholds.ae_error_p10, p90=thresholds.ae_error_p90,
    )
    return thresholds.w1 * transformer_probs + thresholds.w2 * norm_ae
