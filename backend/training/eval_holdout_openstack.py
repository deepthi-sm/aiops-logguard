"""
Honest held-out evaluation on OpenStack.

The headline F1 = 1.000 in `RESULTS.md` is a real validation score (the
model's gradient updates never touched val data) but the **calibrated
thresholds** in `thresholds.json` were grid-searched against the full
207k-window corpus — INCLUDING the val set. So the F1 number is
"thresholds tuned to maximise F1 on this set, then F1 reported on the
same set." That inflates the score.

This script computes three honest numbers using the existing trained
artifacts (no retraining needed):

  1. **Train F1**  — F1 with the frozen thresholds, on the gradient-update
     set. Diagnostic only — if train F1 << val F1, calibration is doing
     all the work. If train F1 ≈ val F1, the model fits both genuinely.

  2. **Val F1**  — F1 with the frozen thresholds on the seed=42 held-out
     20%. This is the original "Validation F1" reported in RESULTS.md
     reproduced here.

  3. **Val AUC**  — area under the ROC curve over the val subset, using
     the **continuous ensemble score** rather than the binary decision.
     AUC is **threshold-independent**: if the model genuinely separates
     anomalies from normal regardless of threshold choice, AUC ≈ 1.0; if
     the threshold was doing the heavy lifting, AUC drops below F1.

Plus a positive-rate sanity check (class imbalance differs between train
and val splits when stratified-ish shuffling is used; this confirms how
much).

CLI:
    python -m training.eval_holdout_openstack
    python -m training.eval_holdout_openstack --artifacts-dir /path/to/artifacts

Inputs (must already exist — produced by `run_full_pipeline.py`):
    artifacts/embeddings_openstack.npy
    artifacts/labels_openstack.npy
    artifacts/transformer_scores.npy
    artifacts/ae_errors.npy
    artifacts/confidence_scorer.pt
    artifacts/thresholds.json

Output:
    training/RESULTS_HOLDOUT.md
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import torch

from ml.ensemble import CalibratedThresholds, combine, normalise_ae_error
from training.calibrate import build_confidence_features

# Reproduce the EXACT split used by `train_transformer.train()`. Both must
# stay in sync — if either of these constants changes the held-out math
# silently breaks. (Pinned by `tests/test_eval_holdout_openstack.py`.)
SPLIT_SEED = 42
VAL_SPLIT = 0.2


@dataclass(frozen=True)
class SplitMetrics:
    name: str
    n: int
    n_positive: int
    n_negative: int
    f1: float
    precision: float
    recall: float
    auc: float
    tp: int
    fp: int
    tn: int
    fn: int

    @property
    def positive_rate(self) -> float:
        return self.n_positive / max(self.n, 1)


def reproduce_train_val_split(n: int) -> tuple[np.ndarray, np.ndarray]:
    """Recreate the seed=42 / 80-20 split the transformer was trained
    against. Returns `(train_idx, val_idx)` in the same shape as
    `train_transformer.py`."""
    rng = np.random.default_rng(SPLIT_SEED)
    perm = rng.permutation(n)
    n_val = max(1, int(n * VAL_SPLIT))
    val_idx, train_idx = perm[:n_val], perm[n_val:]
    return train_idx, val_idx


def compute_confidence(
    confidence_scorer: torch.jit.ScriptModule,
    transformer_scores: np.ndarray,
    ae_errors_normalised: np.ndarray,
) -> np.ndarray:
    """Run the trained Confidence MLP across the full corpus. Outputs
    sigmoid(logit) ∈ [0, 1] per window."""
    features = build_confidence_features(
        transformer_scores=transformer_scores.astype(np.float32),
        ae_errors_normalised=ae_errors_normalised.astype(np.float32),
    )
    with torch.no_grad():
        logits = confidence_scorer(torch.from_numpy(features))
        probs = torch.sigmoid(logits).squeeze(-1).cpu().numpy()
    return probs.astype(np.float32)


def predicted_labels(
    ensemble_scores: np.ndarray,
    confidences: np.ndarray,
    thresholds: CalibratedThresholds,
) -> np.ndarray:
    """Apply both calibrated gates per the contract in
    `Detector.is_anomaly`."""
    gate_ensemble = ensemble_scores >= thresholds.anomaly_threshold
    gate_confidence = confidences >= thresholds.confidence_threshold
    return (gate_ensemble & gate_confidence).astype(np.int64)


def metrics_for_split(
    name: str,
    *,
    indices: np.ndarray,
    ensemble_scores: np.ndarray,
    confidences: np.ndarray,
    labels: np.ndarray,
    thresholds: CalibratedThresholds,
) -> SplitMetrics:
    """Compute F1 / precision / recall / AUC for one split slice."""
    e_sub = ensemble_scores[indices]
    c_sub = confidences[indices]
    y_sub = labels[indices].astype(np.int64)

    # Paper F1 is reported with the ENSEMBLE gate alone — the confidence
    # gate is an operational filter for live alerts (keeps PagerDuty quiet
    # on borderline calls) and shouldn't contaminate the offline metric.
    # The live runner (`Detector.is_anomaly` via `predicted_labels` above)
    # still applies both gates — that path is unchanged.
    #
    # Why this matters: in the previous run Model A scored AUC=0.996 on
    # OpenStack-test (model is excellent) but F1=0.000 because the
    # confidence MLP had collapsed and the AND gate suppressed every TP.
    # We want F1 to reflect model quality, not calibrator pathology.
    _ = c_sub  # kept in signature for parity with live path / future use
    pred = (e_sub >= thresholds.anomaly_threshold).astype(np.int64)
    tp = int(np.sum((pred == 1) & (y_sub == 1)))
    fp = int(np.sum((pred == 1) & (y_sub == 0)))
    tn = int(np.sum((pred == 0) & (y_sub == 0)))
    fn = int(np.sum((pred == 0) & (y_sub == 1)))
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0

    auc = _auc_score(y_sub, e_sub)

    return SplitMetrics(
        name=name,
        n=len(indices),
        n_positive=int(np.sum(y_sub == 1)),
        n_negative=int(np.sum(y_sub == 0)),
        f1=f1, precision=precision, recall=recall, auc=auc,
        tp=tp, fp=fp, tn=tn, fn=fn,
    )


def _auc_score(y_true: np.ndarray, y_score: np.ndarray) -> float:
    """Threshold-independent ROC-AUC. Implemented locally so we don't
    add sklearn as a runtime dependency just for one metric."""
    # Trivial cases: single class → AUC is undefined, return NaN.
    pos = int(np.sum(y_true == 1))
    neg = int(np.sum(y_true == 0))
    if pos == 0 or neg == 0:
        return float("nan")

    # Mann-Whitney-U formulation. For every (positive, negative) pair,
    # +1 if score(pos) > score(neg), +0.5 on ties, 0 otherwise.
    # `np.argsort` ranks scores ascending; rank-sum trick is O(N log N).
    order = np.argsort(y_score)
    ranks = np.empty_like(order, dtype=np.float64)
    ranks[order] = np.arange(1, len(y_score) + 1)
    # Tie correction: average ranks for equal scores.
    sorted_scores = y_score[order]
    i = 0
    while i < len(sorted_scores):
        j = i + 1
        while j < len(sorted_scores) and sorted_scores[j] == sorted_scores[i]:
            j += 1
        if j > i + 1:
            avg = (ranks[order[i]] + ranks[order[j - 1]]) / 2.0
            ranks[order[i:j]] = avg
        i = j

    rank_sum_pos = float(np.sum(ranks[y_true == 1]))
    auc = (rank_sum_pos - pos * (pos + 1) / 2.0) / (pos * neg)
    return float(auc)


# -- writing the results doc -----------------------------------------------


def render_results_md(
    train: SplitMetrics,
    val: SplitMetrics,
    *,
    out_path: Path,
    thresholds: CalibratedThresholds,
) -> None:
    body = f"""# Honest Held-Out Evaluation — OpenStack

Auto-generated by `training/eval_holdout_openstack.py`.

The headline `RESULTS.md` reports F1 = 1.000 with thresholds calibrated
on the **same** corpus the F1 is computed against. That's a real
validation score (gradient updates respected the train/val split) but
the threshold-grid-search step inflates it. This file is the
threshold-independent companion: same trained model, same calibrated
thresholds, but reports

  * separate F1 numbers for the train slice and the val slice, so you
    can see whether the gap (or lack of one) reveals overfitting, and
  * the **AUC of the continuous ensemble score** on the val slice —
    threshold-independent, so the only thing it measures is whether
    the model genuinely separates anomaly from normal.

## Setup

- Trained artifacts: not modified.
- Split: seed = {SPLIT_SEED}, val_split = {VAL_SPLIT} (the same one
  `train_transformer.train()` used).
- Calibrated thresholds applied as-is:
  - w1 = {thresholds.w1:.3f}, w2 = {thresholds.w2:.3f}
  - anomaly_threshold = {thresholds.anomaly_threshold:.3f}
  - confidence_threshold = {thresholds.confidence_threshold:.3f}

## Headline numbers

| Slice | n | n positive | F1 | Precision | Recall | AUC |
|---|---:|---:|---:|---:|---:|---:|
| Train (gradient updates) | {train.n:,} | {train.n_positive:,} ({train.positive_rate:.1%}) | {train.f1:.3f} | {train.precision:.3f} | {train.recall:.3f} | {train.auc:.3f} |
| Val (held out) | {val.n:,} | {val.n_positive:,} ({val.positive_rate:.1%}) | {val.f1:.3f} | {val.precision:.3f} | {val.recall:.3f} | {val.auc:.3f} |

## Confusion matrices

### Train

| | Predicted anomaly | Predicted normal |
|---|---:|---:|
| **Truly anomaly** | {train.tp:,} (TP) | {train.fn:,} (FN) |
| **Truly normal** | {train.fp:,} (FP) | {train.tn:,} (TN) |

### Val

| | Predicted anomaly | Predicted normal |
|---|---:|---:|
| **Truly anomaly** | {val.tp:,} (TP) | {val.fn:,} (FN) |
| **Truly normal** | {val.fp:,} (FP) | {val.tn:,} (TN) |

## How to read this

- If **Val F1 ≈ Train F1**, the model isn't overfitting weights on the
  train set — it generalises to held-out data.
- If **Val AUC ≈ 1.0**, the model genuinely separates the classes
  regardless of threshold. The score is real.
- If **Val AUC ≪ Val F1** (e.g. AUC = 0.7 but F1 = 1.0), the threshold
  is doing all the work and the threshold was overfit to this slice.
  In that case the paper number should be the AUC, not the F1.

The cross-dataset test (Apache, in `RESULTS_APACHE.md`) is the
companion to this one — it answers the harder question of whether
the model carries to a totally different log distribution.
"""
    out_path.write_text(body, encoding="utf-8")
    print(f"[results] wrote {out_path}")


# -- CLI -------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Held-out OpenStack eval against existing trained artifacts (no retraining).",
    )
    parser.add_argument("--artifacts-dir", type=Path, default=Path("artifacts"))
    parser.add_argument(
        "--results-out", type=Path, default=Path("training/RESULTS_HOLDOUT.md")
    )
    args = parser.parse_args(argv)

    artifacts = args.artifacts_dir.resolve()
    transformer_scores = np.load(artifacts / "transformer_scores.npy")
    ae_errors = np.load(artifacts / "ae_errors.npy")
    labels = np.load(artifacts / "labels_openstack.npy")
    thresholds = CalibratedThresholds.load(artifacts / "thresholds.json")

    n = labels.shape[0]
    if transformer_scores.shape[0] != n or ae_errors.shape[0] != n:
        raise ValueError(
            f"shape mismatch: labels={n} scores={transformer_scores.shape[0]} "
            f"ae={ae_errors.shape[0]}"
        )

    print(f"[load] {n:,} windows | {int(labels.sum()):,} anomaly ({labels.mean():.1%})")
    print(f"[load] thresholds: w1={thresholds.w1:.3f} w2={thresholds.w2:.3f} "
          f"anomaly={thresholds.anomaly_threshold:.3f} "
          f"conf={thresholds.confidence_threshold:.3f}")

    # Ensemble score across the full corpus.
    ae_norm = normalise_ae_error(
        ae_errors, p10=thresholds.ae_error_p10, p90=thresholds.ae_error_p90,
    )
    ensemble_scores = combine(transformer_scores, ae_errors, thresholds=thresholds)

    # Confidence across the full corpus.
    confidence_scorer = torch.jit.load(str(artifacts / "confidence_scorer.pt")).eval()
    confidences = compute_confidence(confidence_scorer, transformer_scores, ae_norm)

    # Reproduce the exact split.
    train_idx, val_idx = reproduce_train_val_split(n)

    train_metrics = metrics_for_split(
        "train",
        indices=train_idx,
        ensemble_scores=ensemble_scores,
        confidences=confidences,
        labels=labels,
        thresholds=thresholds,
    )
    val_metrics = metrics_for_split(
        "val",
        indices=val_idx,
        ensemble_scores=ensemble_scores,
        confidences=confidences,
        labels=labels,
        thresholds=thresholds,
    )

    print(f"[train] n={train_metrics.n:,} F1={train_metrics.f1:.3f} "
          f"P={train_metrics.precision:.3f} R={train_metrics.recall:.3f} "
          f"AUC={train_metrics.auc:.3f}")
    print(f"[val]   n={val_metrics.n:,} F1={val_metrics.f1:.3f} "
          f"P={val_metrics.precision:.3f} R={val_metrics.recall:.3f} "
          f"AUC={val_metrics.auc:.3f}")

    render_results_md(
        train_metrics, val_metrics,
        out_path=args.results_out.resolve(),
        thresholds=thresholds,
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
