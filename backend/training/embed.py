"""
Per-template SBERT embeddings + TF-IDF baseline.

Each Window's `templates` (length 20) are embedded INDIVIDUALLY by SBERT,
producing an (N, 20, 384) tensor for the corpus. The transformer attends
across the 20 events; the autoencoder consumes the mean-pooled (N, 384) form.

Caching is critical: SBERT on full OpenStack takes 30–90 minutes on a
Ryzen 5800H CPU. Once produced, embeddings cache to `.npy` files; subsequent
runs reuse the cache and only the cheap downstream steps re-execute. The
training pipeline orchestrator (PR 6) honours these caches automatically.

The TF-IDF baseline isn't used in production. It's persisted alongside SBERT
embeddings purely so the paper has a baseline ("SBERT outperforms TF-IDF on
this task by X% F1").
"""
from __future__ import annotations

from pathlib import Path
from typing import Protocol

import numpy as np

from training.sequence_builder import Window


class SBertLike(Protocol):
    """The subset of SentenceTransformer's API we depend on.

    Defined as a Protocol so unit tests can inject a deterministic mock
    without loading real SBERT weights (~80 MB download per CI run).
    """

    def encode(
        self,
        sentences: list[str],
        batch_size: int = 64,
        normalize_embeddings: bool = True,
        show_progress_bar: bool = False,
    ) -> np.ndarray: ...


# -- SBERT --------------------------------------------------------------

def embed_windows(
    windows: list[Window],
    *,
    model: SBertLike,
    batch_size: int = 128,
) -> np.ndarray:
    """Embed each window's templates and stack into (N, window_len, dim).

    All N*window_len strings are flattened and passed to `model.encode()`
    in a single batched call. SBERT's internal batching makes this 10–50×
    faster than per-window calls — the slow pole of the whole pipeline.
    """
    if not windows:
        return np.empty((0, 0, 0), dtype=np.float32)

    window_len = len(windows[0].templates)
    if any(len(w.templates) != window_len for w in windows):
        raise ValueError("all windows must have the same number of templates")

    flat_texts: list[str] = []
    for w in windows:
        flat_texts.extend(w.templates)

    flat_emb = model.encode(
        flat_texts,
        batch_size=batch_size,
        normalize_embeddings=True,
        show_progress_bar=False,
    )
    flat_emb = np.asarray(flat_emb, dtype=np.float32)
    if flat_emb.ndim != 2:
        raise RuntimeError(f"embedder returned ndim={flat_emb.ndim}, expected 2")
    if flat_emb.shape[0] != len(windows) * window_len:
        raise RuntimeError(
            f"embedder returned {flat_emb.shape[0]} vectors, "
            f"expected {len(windows) * window_len}"
        )

    return flat_emb.reshape(len(windows), window_len, flat_emb.shape[1])


# -- Caching layer (the iteration-loop saver) -----------------------------

def cache_embeddings(emb: np.ndarray, dest: Path) -> None:
    """Save embeddings to `.npy`, creating parent dirs. Idempotent."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    np.save(dest, emb)


def load_cached_embeddings(src: Path) -> np.ndarray | None:
    """Return cached embeddings if present and non-empty, else None."""
    if not src.exists():
        return None
    arr = np.load(src)
    if arr.size == 0:
        return None
    return arr


def embed_or_load(
    windows: list[Window],
    *,
    model: SBertLike,
    cache_path: Path,
    rebuild: bool = False,
    batch_size: int = 128,
) -> np.ndarray:
    """Top-level entry point: load `cache_path` if present, else embed and save.

    Pass `rebuild=True` to force re-embedding (e.g. after data prep changes).
    Each cache hit saves you 30–90 minutes on full OpenStack — don't bypass
    casually.
    """
    if not rebuild:
        cached = load_cached_embeddings(cache_path)
        if cached is not None:
            print(f"[skip] using cached embeddings: {cache_path} {cached.shape}")
            return cached

    print(
        f"[embed] {len(windows):,} windows × "
        f"{len(windows[0].templates) if windows else 0} templates"
    )
    emb = embed_windows(windows, model=model, batch_size=batch_size)
    cache_embeddings(emb, cache_path)
    print(f"[embed] saved {cache_path} {emb.shape}")
    return emb


# -- TF-IDF baseline (paper claim only) -----------------------------------

def build_tfidf_baseline(
    windows: list[Window],
    *,
    max_features: int = 5000,
    ngram_range: tuple[int, int] = (1, 2),
):
    """Fit a TF-IDF vectoriser on window template text. Returns
    `(sparse_matrix, fitted_vectoriser)`.

    sklearn is imported lazily so test files that only exercise the SBERT
    path don't pay the import cost.
    """
    from sklearn.feature_extraction.text import TfidfVectorizer

    texts = [" ".join(w.templates) for w in windows]
    vectoriser = TfidfVectorizer(max_features=max_features, ngram_range=ngram_range)
    matrix = vectoriser.fit_transform(texts)
    return matrix, vectoriser


def cache_tfidf(matrix, dest: Path) -> None:
    """Persist a sparse TF-IDF matrix to `.npz`."""
    import scipy.sparse

    dest.parent.mkdir(parents=True, exist_ok=True)
    scipy.sparse.save_npz(str(dest), matrix)
