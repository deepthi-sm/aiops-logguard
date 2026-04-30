"""
Train the LogAutoEncoder on **normal-only** OpenStack windows.

Step 3.3 (training pipeline) — unsupervised side of the ensemble. Reads
cached SBERT embeddings + per-window labels, mean-pools each window,
filters down to label==0 only, trains the AE on reconstruction loss,
saves a TorchScript artifact at `artifacts/autoencoder.pt`.

Per docs/architecture/training_pipeline.md Step 5:
  * Optimiser: Adam, lr=1e-3
  * Batch size: 256
  * Epochs: 50
  * Loss: MSE
  * Early stop: patience=10 on val reconstruction loss

The whole point of training on normal-only data is that anomalous
sequences produce HIGH reconstruction error at inference. The ensemble
combiner (PR after this) uses that error as the second component.

CLI:
    python -m training.train_autoencoder \\
        --embeddings artifacts/embeddings_openstack.npy \\
        --labels    artifacts/labels_openstack.npy \\
        --out       artifacts/autoencoder.pt
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

from ml.autoencoder import LogAutoEncoder, pool_window

# -- Config ----------------------------------------------------------------

@dataclass
class TrainConfig:
    epochs: int = 50
    batch_size: int = 256
    lr: float = 1e-3
    early_stop_patience: int = 10
    val_split: float = 0.2
    seed: int = 42


# -- Train loop ------------------------------------------------------------

def train(
    embeddings: np.ndarray,
    labels: np.ndarray,
    *,
    config: TrainConfig | None = None,
    device: str = "cpu",
    verbose: bool = True,
) -> tuple[LogAutoEncoder, dict]:
    """Train and return `(model, metrics)`.

    Filters `embeddings` down to rows where `labels == 0` (normal windows
    only) before training. Mean-pools the per-template (B, L, D) input down
    to (B, D) for the AE.

    Returns the best-val-loss model (eager mode) and a metrics dict.
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

    # Filter to normal windows only.
    normal_mask = labels == 0
    if not normal_mask.any():
        raise ValueError(
            "no normal-labelled windows in input — autoencoder needs label==0 data"
        )
    normal_emb = embeddings[normal_mask]
    if verbose:
        print(
            f"[filter] using {normal_emb.shape[0]:,} / {embeddings.shape[0]:,} "
            f"normal windows ({normal_mask.mean() * 100:.1f}%)"
        )

    # Mean-pool to (N, D)
    pooled_t = pool_window(torch.from_numpy(normal_emb).float())
    pooled = pooled_t.numpy()

    # Train/val split
    n = pooled.shape[0]
    perm = rng.permutation(n)
    n_val = max(1, int(n * config.val_split))
    val_idx, train_idx = perm[:n_val], perm[n_val:]
    x_train = torch.from_numpy(pooled[train_idx]).float()
    x_val = torch.from_numpy(pooled[val_idx]).float()

    train_loader = DataLoader(
        TensorDataset(x_train),
        batch_size=config.batch_size,
        shuffle=True,
        drop_last=False,
    )

    model = LogAutoEncoder().to(device)
    optimiser = torch.optim.Adam(model.parameters(), lr=config.lr)

    best_state: dict[str, torch.Tensor] | None = None
    best_val_loss = math.inf
    best_epoch = 0
    epochs_without_improvement = 0
    history: list[dict] = []

    for epoch in range(1, config.epochs + 1):
        model.train()
        train_loss_acc = 0.0
        n_batches = 0
        for (xb,) in train_loader:
            xb = xb.to(device)
            optimiser.zero_grad()
            recon = model(xb)
            loss = F.mse_loss(recon, xb)
            loss.backward()
            optimiser.step()
            train_loss_acc += float(loss.item())
            n_batches += 1

        model.eval()
        with torch.no_grad():
            val_recon = model(x_val.to(device))
            val_loss = float(F.mse_loss(val_recon, x_val.to(device)).item())

        epoch_metrics = {
            "epoch": epoch,
            "train_loss": train_loss_acc / max(n_batches, 1),
            "val_loss": val_loss,
        }
        history.append(epoch_metrics)
        if verbose:
            print(
                f"epoch {epoch:>3} | train MSE {epoch_metrics['train_loss']:.5f} | "
                f"val MSE {val_loss:.5f}"
            )

        if val_loss < best_val_loss:
            best_val_loss = val_loss
            best_epoch = epoch
            best_state = {k: v.detach().clone() for k, v in model.state_dict().items()}
            epochs_without_improvement = 0
        else:
            epochs_without_improvement += 1
            if epochs_without_improvement >= config.early_stop_patience:
                if verbose:
                    print(
                        f"early stop at epoch {epoch} (no val_loss improvement for "
                        f"{config.early_stop_patience} epochs)"
                    )
                break

    if best_state is not None:
        model.load_state_dict(best_state)

    metrics = {
        "best_epoch": best_epoch,
        "best_val_loss": best_val_loss,
        "epochs_run": len(history),
        "n_normal_windows": int(normal_mask.sum()),
        "n_total_windows": int(len(labels)),
        "config": asdict(config),
        "history": history,
    }
    return model, metrics


# -- Save as TorchScript ---------------------------------------------------

def save_torchscript(model: LogAutoEncoder, dest: Path) -> None:
    """Eval-mode TorchScript export — the live detector loads `.pt` without
    importing this module."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    model.eval()
    scripted = torch.jit.script(model)
    scripted.save(str(dest))


# -- CLI -------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Train LogAutoEncoder on normal-only window embeddings.",
    )
    parser.add_argument("--embeddings", type=Path, required=True,
                        help="Path to embeddings .npy (N, 20, 384).")
    parser.add_argument("--labels", type=Path, required=True,
                        help="Path to labels .npy (N,) binary — only label==0 are used.")
    parser.add_argument("--out", type=Path, default=Path("artifacts/autoencoder.pt"))
    parser.add_argument("--metrics-out", type=Path,
                        default=Path("artifacts/autoencoder_metrics.json"))
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
    print(
        f"        best_val_loss={metrics['best_val_loss']:.5f} at epoch {metrics['best_epoch']}"
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
