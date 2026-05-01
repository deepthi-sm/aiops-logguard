"""
Live anomaly detector — loads the three TorchScript artifacts produced by
the training pipeline (`transformer.pt`, `autoencoder.pt`,
`confidence_scorer.pt`) plus the calibrated `thresholds.json`, and scores
one window at a time.

This module is intentionally pure compute: it knows nothing about Redis,
Postgres, or websockets. Step 4b's runner composes it with the consumer
(Step 4a) and the persistence + broadcast layers (Step 4b-ii / 4b-iii).

Single source of truth:

  * Embedding shape: (window_len, sbert_dim) = (20, 384) — produced by
    `ml.embedder.embed_window`. The transformer is fed (1, 20, 384) and
    the autoencoder is fed mean-pooled (1, 384).
  * Ensemble combine + AE-error normalisation: re-uses `ml.ensemble`
    so live and training-time evaluation execute the same code.
  * Confidence features: re-uses `training.calibrate.build_confidence_features`
    so the (4,)-vector packed at inference matches what the MLP was trained on.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import torch

from ml.ensemble import CalibratedThresholds, combine, normalise_ae_error
from training.calibrate import build_confidence_features

ARTIFACT_TRANSFORMER = "transformer.pt"
ARTIFACT_AUTOENCODER = "autoencoder.pt"
ARTIFACT_CONFIDENCE = "confidence_scorer.pt"
ARTIFACT_THRESHOLDS = "thresholds.json"


@dataclass(frozen=True)
class DetectionResult:
    """All numeric outputs the postprocess layer needs from a single window.

    All fields are plain Python floats / ints (not torch / numpy) so the
    rest of the system can serialise this without leaking ML types.
    """
    # Combined ensemble score in [0, 1]. Compare to thresholds.anomaly_threshold.
    ensemble_score: float
    # Component scores (kept for transparency / debugging / metrics).
    transformer_prob: float       # sigmoid of anomaly_logit
    ae_error_raw: float           # raw MSE
    ae_error_normalised: float    # after percentile clip-and-scale
    # Output of the confidence MLP (sigmoid of its logit).
    confidence: float
    # Failure regressor output, rounded to int minutes; None when not a
    # critical-class detection (postprocess decides whether to surface it).
    predicted_failure_minutes: int
    # Per-event saliency, one float per template in the window. Sums to ~1.
    # Frontend renders the top-N as `top_contributing_lines`.
    attention: tuple[float, ...]

    @property
    def is_anomaly(self) -> bool:
        """Convenience: requires this to be precomputed against the loaded
        thresholds, so we keep `Detector.is_anomaly(detection)` separate."""
        raise NotImplementedError(
            "Use Detector.is_anomaly(detection) — DetectionResult doesn't "
            "carry the thresholds alone."
        )


class Detector:
    """Stateful detector — torch modules + thresholds, loaded once at boot.

    Construct via `from_artifacts(artifacts_dir)` for production. Tests
    that don't want to torch-jit a fake model can pass already-loaded
    `torch.jit.ScriptModule` instances directly to `__init__`.
    """

    def __init__(
        self,
        transformer: torch.jit.ScriptModule | torch.nn.Module,
        autoencoder: torch.jit.ScriptModule | torch.nn.Module,
        confidence_scorer: torch.jit.ScriptModule | torch.nn.Module,
        thresholds: CalibratedThresholds,
    ) -> None:
        for m in (transformer, autoencoder, confidence_scorer):
            m.eval()
        self._transformer = transformer
        self._autoencoder = autoencoder
        self._confidence = confidence_scorer
        self._thresholds = thresholds

    @classmethod
    def from_artifacts(cls, artifacts_dir: Path | str) -> Detector:
        artifacts_dir = Path(artifacts_dir)
        for fname in (
            ARTIFACT_TRANSFORMER,
            ARTIFACT_AUTOENCODER,
            ARTIFACT_CONFIDENCE,
            ARTIFACT_THRESHOLDS,
        ):
            if not (artifacts_dir / fname).exists():
                raise FileNotFoundError(
                    f"missing required artifact: {artifacts_dir / fname}\n"
                    "  Run `python -m training.run_full_pipeline --dataset openstack` first."
                )
        transformer = torch.jit.load(str(artifacts_dir / ARTIFACT_TRANSFORMER))
        autoencoder = torch.jit.load(str(artifacts_dir / ARTIFACT_AUTOENCODER))
        confidence = torch.jit.load(str(artifacts_dir / ARTIFACT_CONFIDENCE))
        thresholds = CalibratedThresholds.load(artifacts_dir / ARTIFACT_THRESHOLDS)
        return cls(
            transformer=transformer,
            autoencoder=autoencoder,
            confidence_scorer=confidence,
            thresholds=thresholds,
        )

    @property
    def thresholds(self) -> CalibratedThresholds:
        return self._thresholds

    def is_anomaly(self, detection: DetectionResult) -> bool:
        """Apply the calibrated thresholds. Both gates must pass."""
        return (
            detection.ensemble_score >= self._thresholds.anomaly_threshold
            and detection.confidence >= self._thresholds.confidence_threshold
        )

    @torch.no_grad()
    def score(self, window_embedding: np.ndarray) -> DetectionResult:
        """Score one window.

        Args:
            window_embedding: (window_len, sbert_dim) — output of
                `ml.embedder.embed_window`.

        Returns:
            A DetectionResult with every signal the postprocess layer
            needs. Use `is_anomaly(...)` to apply the binary gate.
        """
        if window_embedding.ndim != 2:
            raise ValueError(
                f"expected 2-D embedding (window_len, sbert_dim), got "
                f"shape {window_embedding.shape}"
            )

        x = torch.from_numpy(window_embedding).float().unsqueeze(0)  # (1, L, D)

        # Transformer
        transformer_out = self._transformer(x)
        anomaly_logit = transformer_out["anomaly_logit"]      # (1, 1)
        failure_minutes = transformer_out["failure_minutes"]  # (1, 1)
        attention = transformer_out["attention"]              # (1, L)

        transformer_prob = float(torch.sigmoid(anomaly_logit).item())
        failure_min_raw = float(failure_minutes.item())
        # Failure regressor occasionally goes slightly negative or NaN;
        # clamp to a sensible non-negative integer.
        if not math.isfinite(failure_min_raw) or failure_min_raw < 0:
            failure_min_int = 0
        else:
            failure_min_int = int(round(failure_min_raw))
        attention_tuple = tuple(float(a) for a in attention.squeeze(0).tolist())

        # Autoencoder — feed mean-pooled embedding
        pooled = x.mean(dim=1)  # (1, D)
        recon = self._autoencoder(pooled)
        ae_error_raw = float(((recon - pooled) ** 2).mean().item())

        # Ensemble score (re-use training's combine + normaliser)
        ae_error_norm_arr = normalise_ae_error(
            np.array([ae_error_raw], dtype=np.float32),
            p10=self._thresholds.ae_error_p10,
            p90=self._thresholds.ae_error_p90,
        )
        ensemble_score_arr = combine(
            transformer_probs=np.array([transformer_prob], dtype=np.float32),
            ae_errors=np.array([ae_error_raw], dtype=np.float32),
            thresholds=self._thresholds,
        )
        ensemble_score = float(ensemble_score_arr[0])
        ae_error_norm = float(ae_error_norm_arr[0])

        # Confidence MLP — features are (transformer_score, ae_error_normalised,
        # seq_len_norm=0, time_of_day_norm=0). Same pack as training/calibrate.
        features = build_confidence_features(
            transformer_scores=np.array([transformer_prob], dtype=np.float32),
            ae_errors_normalised=np.array([ae_error_norm], dtype=np.float32),
        )
        conf_logit = self._confidence(torch.from_numpy(features))
        confidence = float(torch.sigmoid(conf_logit).item())

        return DetectionResult(
            ensemble_score=ensemble_score,
            transformer_prob=transformer_prob,
            ae_error_raw=ae_error_raw,
            ae_error_normalised=ae_error_norm,
            confidence=confidence,
            predicted_failure_minutes=failure_min_int,
            attention=attention_tuple,
        )
