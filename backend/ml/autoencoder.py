"""
Symmetric MLP autoencoder over mean-pooled SBERT window embeddings.

Trained on **normal sequences only** — the whole point is that anomalous
sequences produce high reconstruction error. The ensemble layer combines
this with the Transformer's anomaly score:

    combined = w1 * sigmoid(transformer.anomaly_logit) + w2 * normalize(ae_error)

The Transformer captures sequence-level patterns; the AE captures
distributional drift at the window level. They fail in different ways, so
the ensemble is more robust than either alone.

Saved as TorchScript (`artifacts/autoencoder.pt`).
"""
from __future__ import annotations

import torch
from torch import nn

from ml.transformer import SBERT_DIM

D_BOTTLENECK = 64


class LogAutoEncoder(nn.Module):
    """384 → 256 → 128 → 64 → 128 → 256 → 384.

    Operates on a single (d_input,) vector per window — the caller is
    responsible for mean-pooling the per-template embeddings before forward.
    The transformer is the heavy lifter for sequence context; this AE just
    needs a good "is this normal" signal at the window level.
    """

    def __init__(
        self,
        *,
        d_input: int = SBERT_DIM,
        d_bottleneck: int = D_BOTTLENECK,
    ) -> None:
        super().__init__()
        self.d_input = d_input
        self.d_bottleneck = d_bottleneck

        self.encoder = nn.Sequential(
            nn.Linear(d_input, 256),
            nn.ReLU(),
            nn.Linear(256, 128),
            nn.ReLU(),
            nn.Linear(128, d_bottleneck),
        )
        self.decoder = nn.Sequential(
            nn.Linear(d_bottleneck, 128),
            nn.ReLU(),
            nn.Linear(128, 256),
            nn.ReLU(),
            nn.Linear(256, d_input),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """Args: x of shape (B, d_input). Returns reconstruction of same shape."""
        if x.dim() != 2 or x.size(1) != self.d_input:
            raise ValueError(
                f"expected (B, {self.d_input}), got dim={x.dim()} size1={x.size(1) if x.dim() > 1 else -1}"
            )
        z = self.encoder(x)
        return self.decoder(z)


def reconstruction_error(model: LogAutoEncoder, x: torch.Tensor) -> torch.Tensor:
    """Per-window MSE reconstruction error. Shape (B,).

    Used both during training (validation early-stop signal) and inference
    (input to the ensemble combiner).
    """
    with torch.no_grad():
        recon = model(x)
    return torch.mean((recon - x) ** 2, dim=1)


def pool_window(x: torch.Tensor) -> torch.Tensor:
    """Mean-pool a per-template embedding sequence to a single window vector.

    Args:
        x: shape (B, window_len, d_input) — output of the embedder.
    Returns:
        shape (B, d_input) — input to LogAutoEncoder.forward().
    """
    if x.ndim != 3:
        raise ValueError(f"expected (B, window_len, d_input), got {tuple(x.shape)}")
    return x.mean(dim=1)
