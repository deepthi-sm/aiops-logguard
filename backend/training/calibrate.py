"""
Calibration: pick the ensemble's mixing weights and the per-window thresholds,
plus train a small confidence MLP that gates noisy predictions.

This is the layer that turns "two raw scores from two models" into "an actual
yes/no anomaly decision the alerting layer can trust." Per
docs/architecture/training_pipeline.md Step 6:

    combined_score   = w1 * transformer_score + w2 * normalised_ae_error
    is_anomaly       = combined_score > anomaly_threshold
                       AND confidence > confidence_threshold

Outputs:
  * `artifacts/thresholds.json` — `{w1, w2, anomaly_threshold, confidence_threshold}`
  * `artifacts/confidence_scorer.pt` — small TorchScript MLP

CLI:
    python -m training.calibrate \\
        --transformer-scores artifacts/transformer_scores.npy \\
        --ae-errors          artifacts/ae_errors.npy \\
        --labels             artifacts/labels.npy \\
        --thresholds-out     artifacts/thresholds.json \\
        --confidence-out     artifacts/confidence_scorer.pt
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F
from torch import nn

from ml.ensemble import normalise_ae_error

# -- F1 grid search for (w1, threshold) -----------------------------------

def _binary_f1(probs: np.ndarray, labels: np.ndarray, threshold: float) -> tuple[float, float, float]:
    preds = (probs >= threshold).astype(np.int64)
    labels = labels.astype(np.int64)
    tp = int(((preds == 1) & (labels == 1)).sum())
    fp = int(((preds == 1) & (labels == 0)).sum())
    fn = int(((preds == 0) & (labels == 1)).sum())
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    return f1, precision, recall


@dataclass
class GridSearchResult:
    w1: float
    w2: float
    anomaly_threshold: float
    f1: float
    precision: float
    recall: float


def grid_search(
    transformer_scores: np.ndarray,
    ae_errors_normalised: np.ndarray,
    labels: np.ndarray,
    *,
    w1_values: np.ndarray | None = None,
    threshold_values: np.ndarray | None = None,
) -> GridSearchResult:
    """Exhaustive search over (w1, threshold) maximising F1. `w2 = 1 - w1`.

    Defaults:
      w1 ∈ {0.30, 0.35, ..., 0.90}    (13 values)
      threshold ∈ {0.30, 0.35, ..., 0.90}
    """
    if w1_values is None:
        w1_values = np.linspace(0.30, 0.90, 13)
    if threshold_values is None:
        threshold_values = np.linspace(0.30, 0.90, 13)

    if transformer_scores.shape != ae_errors_normalised.shape:
        raise ValueError("transformer_scores and ae_errors must have the same shape")
    if labels.shape != transformer_scores.shape:
        raise ValueError("labels must match scores shape")

    best = GridSearchResult(
        w1=float(w1_values[0]),
        w2=1.0 - float(w1_values[0]),
        anomaly_threshold=float(threshold_values[0]),
        f1=-1.0,
        precision=0.0,
        recall=0.0,
    )
    for w1 in w1_values:
        w2 = 1.0 - float(w1)
        combined = float(w1) * transformer_scores + w2 * ae_errors_normalised
        for thresh in threshold_values:
            f1, p, r = _binary_f1(combined, labels, float(thresh))
            if f1 > best.f1:
                best = GridSearchResult(
                    w1=float(w1),
                    w2=float(w2),
                    anomaly_threshold=float(thresh),
                    f1=f1,
                    precision=p,
                    recall=r,
                )
    return best


# -- Confidence MLP --------------------------------------------------------

CONFIDENCE_INPUT_DIM = 4   # (transformer_score, ae_error_normalised, seq_len_norm, time_of_day_norm)


class ConfidenceScorer(nn.Module):
    """Predicts P(prediction is correct) given raw signals.

    Trained with BCE: target = 1 if combined-score-based prediction matches
    the ground-truth label, else 0. At inference, low confidence → suppress
    the alert (keeps PagerDuty quiet on borderline calls).
    """

    def __init__(self, d_input: int = CONFIDENCE_INPUT_DIM) -> None:
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(d_input, 32),
            nn.ReLU(),
            nn.Linear(32, 16),
            nn.ReLU(),
            nn.Linear(16, 1),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        # Returns LOGITS — apply sigmoid at inference to get probability.
        return self.net(x)


def build_confidence_features(
    transformer_scores: np.ndarray,
    ae_errors_normalised: np.ndarray,
    *,
    seq_len_norm: np.ndarray | None = None,
    time_of_day_norm: np.ndarray | None = None,
) -> np.ndarray:
    """Pack the four confidence features into a (N, 4) array.

    Missing features are filled with zeros. OpenStack training doesn't ship
    seq_len or time_of_day signals; these can be wired in by the live
    detector at inference if available.
    """
    n = transformer_scores.shape[0]
    if seq_len_norm is None:
        seq_len_norm = np.zeros(n, dtype=np.float32)
    if time_of_day_norm is None:
        time_of_day_norm = np.zeros(n, dtype=np.float32)
    return np.stack(
        [transformer_scores, ae_errors_normalised, seq_len_norm, time_of_day_norm],
        axis=1,
    ).astype(np.float32)


def train_confidence_scorer(
    features: np.ndarray,
    correctness_targets: np.ndarray,  # 1 if prediction was correct, else 0
    *,
    epochs: int = 20,
    batch_size: int = 64,
    lr: float = 1e-3,
    seed: int = 42,
    device: str = "cpu",
    verbose: bool = True,
) -> tuple[ConfidenceScorer, dict]:
    """Train and return (model, metrics)."""
    torch.manual_seed(seed)
    rng = np.random.default_rng(seed)

    n = features.shape[0]
    perm = rng.permutation(n)
    n_val = max(1, int(n * 0.2))
    val_idx, train_idx = perm[:n_val], perm[n_val:]
    x_train = torch.from_numpy(features[train_idx]).float()
    y_train = torch.from_numpy(correctness_targets[train_idx]).float()
    x_val = torch.from_numpy(features[val_idx]).float()
    y_val = torch.from_numpy(correctness_targets[val_idx]).float()

    model = ConfidenceScorer().to(device)
    optimiser = torch.optim.Adam(model.parameters(), lr=lr)

    history: list[dict] = []
    best_val_loss = float("inf")
    best_state: dict[str, torch.Tensor] | None = None
    for epoch in range(1, epochs + 1):
        model.train()
        # Simple full-batch is fine — confidence training is tiny.
        idx = torch.randperm(x_train.shape[0])
        train_loss_acc = 0.0
        n_batches = 0
        for start in range(0, x_train.shape[0], batch_size):
            xb = x_train[idx[start : start + batch_size]].to(device)
            yb = y_train[idx[start : start + batch_size]].to(device)
            optimiser.zero_grad()
            logits = model(xb).squeeze(-1)
            loss = F.binary_cross_entropy_with_logits(logits, yb)
            loss.backward()
            optimiser.step()
            train_loss_acc += float(loss.item())
            n_batches += 1

        model.eval()
        with torch.no_grad():
            val_logits = model(x_val.to(device)).squeeze(-1)
            val_loss = float(
                F.binary_cross_entropy_with_logits(val_logits, y_val.to(device)).item()
            )
        history.append({
            "epoch": epoch,
            "train_loss": train_loss_acc / max(n_batches, 1),
            "val_loss": val_loss,
        })
        if verbose:
            print(f"confidence epoch {epoch:>2} | val BCE {val_loss:.4f}")
        if val_loss < best_val_loss:
            best_val_loss = val_loss
            best_state = {k: v.detach().clone() for k, v in model.state_dict().items()}

    if best_state is not None:
        model.load_state_dict(best_state)

    return model, {"best_val_loss": best_val_loss, "history": history}


def pick_confidence_threshold(
    model: ConfidenceScorer,
    features: np.ndarray,
    correctness_targets: np.ndarray,
    *,
    candidates: np.ndarray | None = None,
    device: str = "cpu",
) -> float:
    """Choose the confidence-threshold that maximises F1 of the
    correctness-prediction task on the held-out portion."""
    if candidates is None:
        candidates = np.linspace(0.3, 0.9, 13)
    model.eval()
    with torch.no_grad():
        probs = torch.sigmoid(model(torch.from_numpy(features).float().to(device))).squeeze(-1).cpu().numpy()
    best_t, best_f1 = float(candidates[0]), -1.0
    for t in candidates:
        f1, _, _ = _binary_f1(probs, correctness_targets, float(t))
        if f1 > best_f1:
            best_f1 = f1
            best_t = float(t)
    return best_t


# -- TorchScript save -----------------------------------------------------

def save_confidence_torchscript(model: ConfidenceScorer, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    model.eval()
    scripted = torch.jit.script(model)
    scripted.save(str(dest))


def save_thresholds(
    result: GridSearchResult,
    confidence_threshold: float,
    *,
    ae_error_p10: float,
    ae_error_p90: float,
    dest: Path,
) -> None:
    """Write `thresholds.json` in the format `ml.ensemble.CalibratedThresholds`
    expects to load."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "w1": result.w1,
        "w2": result.w2,
        "anomaly_threshold": result.anomaly_threshold,
        "confidence_threshold": confidence_threshold,
        "ae_error_p10": ae_error_p10,
        "ae_error_p90": ae_error_p90,
    }
    with dest.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)


# -- One-shot calibrate() ------------------------------------------------

def calibrate(
    transformer_scores: np.ndarray,
    ae_errors: np.ndarray,
    labels: np.ndarray,
    *,
    thresholds_out: Path,
    confidence_out: Path,
    device: str = "cpu",
    verbose: bool = True,
) -> dict:
    """Top-level entrypoint used by the orchestrator. Returns a metrics dict."""
    # Compute p10 / p90 once so both calibration AND the live detector use
    # the identical normalisation contract from ml.ensemble.
    ae_error_p10 = float(np.percentile(ae_errors, 10))
    ae_error_p90 = float(np.percentile(ae_errors, 90))
    ae_norm = normalise_ae_error(ae_errors, p10=ae_error_p10, p90=ae_error_p90)
    grid = grid_search(transformer_scores, ae_norm, labels)
    if verbose:
        print(
            f"[grid] w1={grid.w1:.2f}  w2={grid.w2:.2f}  "
            f"thresh={grid.anomaly_threshold:.2f}  F1={grid.f1:.3f}"
        )

    # -- Confidence target: DIRECTIONAL margin from the decision boundary ----
    #
    # Two prior bugs we are jointly correcting here:
    #
    #   v1 (`correctness = (preds == labels)`): degenerated to all-1s on a
    #   high-F1 grid, MLP learned a constant high logit, live DB confidence
    #   was MIN=MAX=AVG=1.0000 across 4908+ rows.
    #
    #   v2 (`margin_target = |combined - threshold|`): direction-blind. With
    #   class imbalance the MLP learned that decisive *negatives* (well
    #   below threshold) deserved high confidence — so on the eval grid
    #   `mean_conf(TP)=0.024` vs `mean_conf(TN)=0.354`, the AND gate
    #   (`ensemble ≥ τ_a AND confidence ≥ τ_c`) suppressed every true
    #   positive on Model A → F1=0.000 even though AUC=0.996. Diagnosed
    #   via `_diagnose_eval.py`.
    #
    # The fix: multiply the margin by `correct ∈ {0, 1}`. A *correct*
    # decisive prediction gets a high target; a *wrong* decisive prediction
    # gets target=0 even though its margin is large. This is what the live
    # confidence gate actually needs to filter out.
    #
    # Doesn't degenerate at high F1 (correct=1 still varies via margin).
    # Respects direction (wrong predictions get target=0). Lives are saved.
    combined = grid.w1 * transformer_scores + grid.w2 * ae_norm
    preds = (combined >= grid.anomaly_threshold).astype(np.int64)
    correct = (preds == labels.astype(np.int64)).astype(np.float32)
    distance = np.abs(combined - grid.anomaly_threshold)
    max_distance = max(grid.anomaly_threshold, 1.0 - grid.anomaly_threshold)
    margin = np.clip(distance / max_distance, 0.0, 1.0).astype(np.float32)
    directional_target = (correct * margin).astype(np.float32)

    features = build_confidence_features(transformer_scores, ae_norm)
    confidence_model, conf_metrics = train_confidence_scorer(
        features, directional_target, device=device, verbose=verbose
    )
    confidence_threshold = pick_confidence_threshold(
        confidence_model, features, directional_target, device=device
    )
    save_confidence_torchscript(confidence_model, confidence_out)
    save_thresholds(
        grid, confidence_threshold,
        ae_error_p10=ae_error_p10,
        ae_error_p90=ae_error_p90,
        dest=thresholds_out,
    )
    if verbose:
        print(f"[done] thresholds={thresholds_out}  confidence={confidence_out}")
    return {
        "ensemble": {
            "w1": grid.w1,
            "w2": grid.w2,
            "anomaly_threshold": grid.anomaly_threshold,
            "ae_error_p10": ae_error_p10,
            "ae_error_p90": ae_error_p90,
            "f1": grid.f1,
            "precision": grid.precision,
            "recall": grid.recall,
        },
        "confidence": {
            "threshold": confidence_threshold,
            "best_val_loss": conf_metrics["best_val_loss"],
        },
    }


# -- CLI ------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Calibrate ensemble + train confidence MLP.")
    parser.add_argument("--transformer-scores", type=Path, required=True)
    parser.add_argument("--ae-errors", type=Path, required=True)
    parser.add_argument("--labels", type=Path, required=True)
    parser.add_argument("--thresholds-out", type=Path, default=Path("artifacts/thresholds.json"))
    parser.add_argument("--confidence-out", type=Path, default=Path("artifacts/confidence_scorer.pt"))
    parser.add_argument("--metrics-out", type=Path, default=Path("artifacts/calibration_metrics.json"))
    parser.add_argument("--device", default="cpu")
    args = parser.parse_args(argv)

    transformer_scores = np.load(args.transformer_scores)
    ae_errors = np.load(args.ae_errors)
    labels = np.load(args.labels)

    metrics = calibrate(
        transformer_scores,
        ae_errors,
        labels,
        thresholds_out=args.thresholds_out,
        confidence_out=args.confidence_out,
        device=args.device,
    )
    args.metrics_out.parent.mkdir(parents=True, exist_ok=True)
    with args.metrics_out.open("w", encoding="utf-8") as f:
        json.dump(metrics, f, indent=2)
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
