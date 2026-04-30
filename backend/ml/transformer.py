"""
Two-headed Transformer encoder for log anomaly detection + failure prediction.

Per docs/architecture/system_overview.md (Layer 4a) and
docs/architecture/training_pipeline.md (Step 4):

  * 4 layers, 8 attention heads, d_model=256, dropout=0.1
  * Input: per-template SBERT embeddings — shape (B, WINDOW_LEN, SBERT_DIM)
    (i.e. each event in the 20-line window is embedded individually so the
    transformer can attend across events; this is the standard log-anomaly
    setup used by DeepLog / LogBERT and the Phase 1 paper baselines.)
  * Mean-pool over the window, then two heads:
      - Anomaly classifier (binary cross-entropy, sigmoid at inference)
      - Failure-window regressor (MSE; only known-failure windows contribute)
  * Per-event saliency exposed at inference for the explainability path
    (frontend's `top_contributing_lines` is rendered from this).

Saved as TorchScript (`artifacts/transformer.pt`) so the live detector loads
the `.pt` without importing this module — see CLAUDE.md hard rule
"Don't bake artifacts into Docker images."
"""
from __future__ import annotations

import torch
from torch import nn

# -- Canonical hyperparameters ---------------------------------------------
# Bound into the trained checkpoint — change these and you must retrain
# (saved .pt files have fixed shapes; live detector will fail to load).

WINDOW_LEN = 20         # must match training/sequence_builder.WINDOW_SIZE
SBERT_DIM = 384         # all-MiniLM-L6-v2 output dimensionality
D_MODEL = 256
N_HEADS = 8
N_LAYERS = 4
DROPOUT = 0.1


class LogTransformer(nn.Module):
    """Transformer encoder over per-template SBERT embeddings.

    Forward returns a dict of three tensors so TorchScript can serialise it
    cleanly (dataclass returns aren't JIT-friendly):

        anomaly_logit:    (B, 1)   — pass through sigmoid for prob in [0, 1]
        failure_minutes:  (B, 1)   — only meaningful for known-failure windows
        attention:        (B, L)   — per-event normalised saliency (sums to 1)
    """

    def __init__(
        self,
        *,
        d_input: int = SBERT_DIM,
        d_model: int = D_MODEL,
        n_heads: int = N_HEADS,
        n_layers: int = N_LAYERS,
        dropout: float = DROPOUT,
        window_len: int = WINDOW_LEN,
    ) -> None:
        super().__init__()
        self.window_len = window_len
        self.d_input = d_input
        self.d_model = d_model

        self.input_proj = nn.Linear(d_input, d_model)
        # Learned positional encoding — cheap (20×256 = 5K params) and easier
        # to tune than sinusoidal during 30-epoch fine-tunes.
        self.pos_embedding = nn.Parameter(torch.randn(1, window_len, d_model) * 0.02)

        encoder_layer = nn.TransformerEncoderLayer(
            d_model=d_model,
            nhead=n_heads,
            dim_feedforward=4 * d_model,
            dropout=dropout,
            batch_first=True,
            activation="gelu",
        )
        self.encoder = nn.TransformerEncoder(encoder_layer, num_layers=n_layers)
        self.pre_pool_norm = nn.LayerNorm(d_model)

        self.anomaly_head = nn.Linear(d_model, 1)
        self.failure_head = nn.Linear(d_model, 1)

    def forward(self, x: torch.Tensor) -> dict[str, torch.Tensor]:
        """Args:
            x: SBERT embeddings, shape (B, window_len, d_input).
        """
        # Use size()/dim() rather than shape/ndim so the TorchScript exporter
        # can infer types statically.
        if x.dim() != 3:
            raise ValueError(f"expected 3-D input (B, L, d_input), got dim={x.dim()}")
        if x.size(1) != self.window_len:
            raise ValueError(f"expected window_len={self.window_len}, got {x.size(1)}")
        if x.size(2) != self.d_input:
            raise ValueError(f"expected d_input={self.d_input}, got {x.size(2)}")

        h = self.input_proj(x)                          # (B, L, d_model)
        h = h + self.pos_embedding                      # broadcast positional info
        h = self.encoder(h)                             # (B, L, d_model)
        h = self.pre_pool_norm(h)

        # Per-event saliency: L2 norm of each contextualised representation,
        # normalised across the window so weights sum to 1. This is a
        # well-behaved proxy for explainability that's easier to extract
        # through TorchScript than raw multi-head attention weights.
        # `torch.linalg.norm` is unambiguous to the TorchScript exporter
        # (h.norm has overload-resolution issues under jit.script).
        attention = torch.linalg.norm(h, dim=-1)                                # (B, L)
        attention = attention / attention.sum(dim=-1, keepdim=True).clamp(min=1e-8)

        pooled = h.mean(dim=1)                          # (B, d_model)

        return {
            "anomaly_logit": self.anomaly_head(pooled),
            "failure_minutes": self.failure_head(pooled),
            "attention": attention,
        }
