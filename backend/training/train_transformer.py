"""
Train the LogTransformer on labelled OpenStack windows.

Step 3.3 (training pipeline) — supervised training. Reads cached SBERT
embeddings + per-window labels, trains the two-headed transformer, saves
a TorchScript artifact at `artifacts/transformer.pt`.

Per docs/architecture/training_pipeline.md Step 4:
  * Optimiser: AdamW, lr=2e-4, weight_decay=0.01
  * Schedule: cosine annealing
  * Batch size: 64, epochs: 30
  * Early stop: patience=5 on validation F1
  * Loss: BCE for anomaly head + MSE for failure-window head
    (MSE only contributes when failure_minutes is provided)

CLI:
    python -m training.train_transformer \\
        --embeddings artifacts/embeddings_openstack.npy \\
        --labels    artifacts/labels_openstack.npy \\
        --out       artifacts/transformer.pt
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F
from torch.utils.data import DataLoader, TensorDataset

from ml.transformer import LogTransformer

# -- Config ----------------------------------------------------------------

@dataclass
class TrainConfig:
    epochs: int = 30
    batch_size: int = 64
    lr: float = 2e-4
    weight_decay: float = 0.01
    early_stop_patience: int = 5
    val_split: float = 0.2
    seed: int = 42
    # Class-weighted BCE — counters the trivial-classifier collapse that BCE
    # falls into on imbalanced data. Auto-computed from the train split as
    # `n_negatives / n_positives` and capped at 100. Disable for experiments
    # where you want vanilla BCE behaviour.
    use_pos_weight: bool = True
    pos_weight_cap: float = 100.0


# -- Loss ------------------------------------------------------------------

def _two_headed_loss(
    outputs: dict[str, torch.Tensor],
    anomaly_targets: torch.Tensor,        # (B,) float in {0, 1}
    failure_targets: torch.Tensor | None,  # (B,) minutes-to-failure
    failure_mask: torch.Tensor | None,     # (B,) bool — True where failure_targets is meaningful
    *,
    pos_weight: torch.Tensor | None = None,  # (1,) scalar — multiplies positive-class loss
) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
    """Returns (total_loss, bce_component, mse_component).

    Failure regression is masked so OpenStack (which has no time-to-failure
    labels) trains only the anomaly head. The mse component is reported as
    zero in that case but the head still runs forward — it just doesn't
    receive gradient.

    `pos_weight` is multiplied into the positive class's BCE loss. With
    realistic class imbalance (~9% positives on full OpenStack) vanilla BCE
    converges to "predict 0 for everything" — non-zero pos_weight reweights
    the loss so positives matter proportionally to their rarity.
    """
    anomaly_logit = outputs["anomaly_logit"].squeeze(-1)
    bce = F.binary_cross_entropy_with_logits(
        anomaly_logit, anomaly_targets, pos_weight=pos_weight,
    )

    if failure_targets is not None and failure_mask is not None and failure_mask.any():
        failure_pred = outputs["failure_minutes"].squeeze(-1)
        mse = F.mse_loss(
            failure_pred[failure_mask],
            failure_targets[failure_mask],
        )
    else:
        mse = torch.zeros((), device=bce.device)

    return bce + mse, bce, mse


# -- Metrics ---------------------------------------------------------------

def _f1_precision_recall(probs: np.ndarray, labels: np.ndarray, threshold: float = 0.5) -> dict:
    """Per-window F1/precision/recall at a fixed threshold (0.5 by default)."""
    preds = (probs >= threshold).astype(np.int64)
    labels = labels.astype(np.int64)
    tp = int(((preds == 1) & (labels == 1)).sum())
    fp = int(((preds == 1) & (labels == 0)).sum())
    fn = int(((preds == 0) & (labels == 1)).sum())
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    return {"f1": f1, "precision": precision, "recall": recall}


# -- Train loop ------------------------------------------------------------

def train(
    embeddings: np.ndarray,
    labels: np.ndarray,
    *,
    failure_minutes: np.ndarray | None = None,
    failure_mask: np.ndarray | None = None,
    config: TrainConfig | None = None,
    device: str = "cpu",
    verbose: bool = True,
) -> tuple[LogTransformer, dict]:
    """Train and return `(model, metrics)`.

    Args:
        embeddings: (N, window_len, sbert_dim) — output of `embed.embed_or_load`.
        labels:     (N,) — 0/1 anomaly labels.
        failure_minutes: optional (N,) — minutes-to-failure regression target.
        failure_mask:    optional (N,) bool — True where failure_minutes is real.
        config:     hyperparameters; defaults to docs/architecture/training_pipeline.md.
        device:     "cpu" or "cuda".
        verbose:    log per-epoch metrics.

    Returns: best-val-F1 model (eager mode) and a metrics dict suitable for
    JSON serialisation into RESULTS.md.
    """
    config = config or TrainConfig()

    if embeddings.ndim != 3:
        raise ValueError(f"embeddings must be (N, L, D), got shape {embeddings.shape}")
    if labels.shape != (embeddings.shape[0],):
        raise ValueError(
            f"labels shape {labels.shape} must be (N={embeddings.shape[0]},)"
        )

    rng = np.random.default_rng(config.seed)
    torch.manual_seed(config.seed)

    # Stratified-ish train/val split: shuffle indices once.
    n = embeddings.shape[0]
    perm = rng.permutation(n)
    n_val = max(1, int(n * config.val_split))
    val_idx, train_idx = perm[:n_val], perm[n_val:]

    x_train = torch.from_numpy(embeddings[train_idx]).float()
    y_train = torch.from_numpy(labels[train_idx]).float()
    x_val = torch.from_numpy(embeddings[val_idx]).float()
    y_val = torch.from_numpy(labels[val_idx]).float()

    if failure_minutes is not None and failure_mask is not None:
        f_train = torch.from_numpy(failure_minutes[train_idx]).float()
        m_train = torch.from_numpy(failure_mask[train_idx]).bool()
    else:
        f_train = None
        m_train = None

    train_loader = DataLoader(
        TensorDataset(x_train, y_train, *(
            (f_train, m_train) if f_train is not None else ()
        )),
        batch_size=config.batch_size,
        shuffle=True,
        drop_last=False,
    )

    # Compute per-batch pos_weight once from the train split. Cap to prevent
    # extreme values on tiny minorities (e.g. 0.1% positives → cap at 100 so
    # gradients stay numerically sane).
    pos_weight: torch.Tensor | None = None
    if config.use_pos_weight:
        n_pos_train = int((y_train == 1).sum().item())
        n_neg_train = int((y_train == 0).sum().item())
        if n_pos_train > 0 and n_neg_train > 0:
            raw_pw = n_neg_train / n_pos_train
            pw_value = min(raw_pw, config.pos_weight_cap)
            pos_weight = torch.tensor([pw_value], device=device)
            if verbose:
                print(
                    f"[pos_weight] n_pos={n_pos_train:,} n_neg={n_neg_train:,} "
                    f"→ pos_weight={pw_value:.2f}"
                )

    model = LogTransformer().to(device)
    optimiser = torch.optim.AdamW(model.parameters(), lr=config.lr, weight_decay=config.weight_decay)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimiser, T_max=config.epochs)

    best_state: dict[str, torch.Tensor] | None = None
    best_val_f1 = -math.inf
    best_epoch = 0
    epochs_without_improvement = 0
    history: list[dict] = []

    for epoch in range(1, config.epochs + 1):
        model.train()
        train_loss_acc = 0.0
        train_bce_acc = 0.0
        train_mse_acc = 0.0
        n_batches = 0
        for batch in train_loader:
            xb = batch[0].to(device)
            yb = batch[1].to(device)
            fb = batch[2].to(device) if len(batch) > 2 else None
            mb = batch[3].to(device) if len(batch) > 3 else None

            optimiser.zero_grad()
            out = model(xb)
            loss, bce, mse = _two_headed_loss(out, yb, fb, mb, pos_weight=pos_weight)
            loss.backward()
            optimiser.step()

            train_loss_acc += float(loss.item())
            train_bce_acc += float(bce.item())
            train_mse_acc += float(mse.item())
            n_batches += 1
        scheduler.step()

        # Validation
        model.eval()
        with torch.no_grad():
            val_out = model(x_val.to(device))
            val_probs = torch.sigmoid(val_out["anomaly_logit"].squeeze(-1)).cpu().numpy()
        val_metrics = _f1_precision_recall(val_probs, y_val.numpy())

        epoch_metrics = {
            "epoch": epoch,
            "train_loss": train_loss_acc / max(n_batches, 1),
            "train_bce": train_bce_acc / max(n_batches, 1),
            "train_mse": train_mse_acc / max(n_batches, 1),
            "val_f1": val_metrics["f1"],
            "val_precision": val_metrics["precision"],
            "val_recall": val_metrics["recall"],
            "lr": scheduler.get_last_lr()[0],
        }
        history.append(epoch_metrics)
        if verbose:
            print(
                f"epoch {epoch:>3} | loss {epoch_metrics['train_loss']:.4f} | "
                f"val F1 {val_metrics['f1']:.3f} (P {val_metrics['precision']:.3f} / "
                f"R {val_metrics['recall']:.3f})"
            )

        if val_metrics["f1"] > best_val_f1:
            best_val_f1 = val_metrics["f1"]
            best_epoch = epoch
            best_state = {k: v.detach().clone() for k, v in model.state_dict().items()}
            epochs_without_improvement = 0
        else:
            epochs_without_improvement += 1
            if epochs_without_improvement >= config.early_stop_patience:
                if verbose:
                    print(f"early stop at epoch {epoch} (no val_f1 improvement for {config.early_stop_patience} epochs)")
                break

    if best_state is not None:
        model.load_state_dict(best_state)

    metrics = {
        "best_epoch": best_epoch,
        "best_val_f1": best_val_f1,
        "best_val_precision": next(h for h in history if h["epoch"] == best_epoch)["val_precision"],
        "best_val_recall": next(h for h in history if h["epoch"] == best_epoch)["val_recall"],
        "epochs_run": len(history),
        "config": asdict(config),
        "history": history,
    }
    return model, metrics


# -- Save as TorchScript ---------------------------------------------------

def save_torchscript(model: LogTransformer, dest: Path) -> None:
    """Eval-mode TorchScript export. The live detector loads the .pt without
    importing this module per CLAUDE.md "Don't bake artifacts into Docker images."
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    model.eval()
    scripted = torch.jit.script(model)
    scripted.save(str(dest))


# -- CLI -------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Train LogTransformer on labelled OpenStack window embeddings.",
    )
    parser.add_argument("--embeddings", type=Path, required=True,
                        help="Path to embeddings .npy (N, 20, 384).")
    parser.add_argument("--labels", type=Path, required=True,
                        help="Path to labels .npy (N,) binary.")
    parser.add_argument("--out", type=Path, default=Path("artifacts/transformer.pt"))
    parser.add_argument("--metrics-out", type=Path,
                        default=Path("artifacts/transformer_metrics.json"),
                        help="Where to write the metrics JSON for RESULTS.md.")
    parser.add_argument("--epochs", type=int, default=TrainConfig.epochs)
    parser.add_argument("--batch-size", type=int, default=TrainConfig.batch_size)
    parser.add_argument("--lr", type=float, default=TrainConfig.lr)
    parser.add_argument("--device", default="cpu")
    args = parser.parse_args(argv)

    embeddings = np.load(args.embeddings)
    labels = np.load(args.labels)
    print(f"[load] embeddings={embeddings.shape} labels={labels.shape}")

    config = TrainConfig(epochs=args.epochs, batch_size=args.batch_size, lr=args.lr)
    model, metrics = train(embeddings, labels, config=config, device=args.device)
    save_torchscript(model, args.out)

    args.metrics_out.parent.mkdir(parents=True, exist_ok=True)
    with args.metrics_out.open("w", encoding="utf-8") as f:
        json.dump(metrics, f, indent=2)
    print(f"[done] saved {args.out} | metrics {args.metrics_out}")
    print(f"        best_val_f1={metrics['best_val_f1']:.3f} at epoch {metrics['best_epoch']}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
