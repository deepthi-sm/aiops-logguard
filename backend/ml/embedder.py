"""
Live SBERT embedder used by the detector.

Embedding logic is the same one training uses (`training.embed.embed_windows`)
applied to a single Window — there's no second copy that can drift. The
canonical contract:

  * Each of the window's 20 templates is embedded INDIVIDUALLY by SBERT
    (not the joined window text). The Transformer attends over the per-event
    embeddings; the AutoEncoder consumes the mean-pooled form.
  * `normalize_embeddings=True` matches training.embed exactly.
  * Output shape: (window_len, sbert_dim) = (20, 384) for all-MiniLM-L6-v2.

Loading the real `sentence-transformers` model is expensive (~80 MB
download on first use, several seconds even when cached). The detector
takes any object satisfying `SBertLike` so tests can inject a stub
embedder without that cost.
"""
from __future__ import annotations

import numpy as np

# Re-export — there is exactly one definition of SBertLike + embed_windows.
from training.embed import SBertLike, embed_windows
from training.sequence_builder import Window

DEFAULT_SBERT_MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"

__all__ = [
    "DEFAULT_SBERT_MODEL_NAME",
    "SBertLike",
    "embed_window",
    "load_default_sbert",
]


def embed_window(window: Window, *, model: SBertLike) -> np.ndarray:
    """Embed one window. Returns (window_len, sbert_dim) — no batch axis.

    Thin convenience wrapper around `training.embed.embed_windows([window])`
    that drops the leading batch dimension. The detector will re-add it
    before feeding the transformer.
    """
    batched = embed_windows([window], model=model)
    if batched.ndim != 3 or batched.shape[0] != 1:
        raise RuntimeError(
            f"unexpected shape from embed_windows: {batched.shape}"
        )
    return batched[0]


def load_default_sbert(model_name: str = DEFAULT_SBERT_MODEL_NAME) -> SBertLike:
    """Lazy-load the production SBERT model.

    Imports `sentence_transformers` here (not at module top) so tests that
    only exercise the stub path don't pay the import cost. First call on a
    fresh machine pulls ~80 MB to the HF cache.
    """
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(model_name)
