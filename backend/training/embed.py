"""
Per-template SBERT embeddings + TF-IDF baseline.

Each Window's `templates` (length 20) are embedded INDIVIDUALLY by SBERT,
producing an (N, 20, 384) tensor for the corpus. The transformer attends
across the 20 events; the autoencoder consumes the mean-pooled (N, 384) form.

Caching is critical: SBERT on full OpenStack takes 30–90 minutes on a
Ryzen 5800H CPU; full HDFS is 10+ hours. Once produced, embeddings cache
to `.npy` files; subsequent runs reuse the cache and only the cheap
downstream steps re-execute.

Why chunked + memmap'd: a previous version flattened ALL N×20 strings
into one Python list and made a single `model.encode()` call with
`show_progress_bar=False`. For full HDFS that's 220 M strings consuming
30+ GB of memory, churning silently for 10+ hours with no log output —
the user thought it was hung. The chunked path embeds 5,000 windows at
a time, writes each chunk to a memmap'd `.npy`, and logs per-chunk
progress with an ETA. A `.progress` sidecar file tracks the next chunk
to embed, so `--resume` picks up exactly where a killed run left off.

The TF-IDF baseline isn't used in production. It's persisted alongside
SBERT embeddings purely so the paper has a baseline ("SBERT outperforms
TF-IDF on this task by X% F1").
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Protocol

import numpy as np

from training.sequence_builder import Window

# Default chunk size. 5,000 windows × 20 templates = 100k strings per
# `model.encode` call — a sweet spot where SBERT's batched GEMM still
# saturates the CPU but Python-list memory stays under ~200 MB.
CHUNK_WINDOWS = 5000


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
    """Embed each window's templates into (N, window_len, dim).

    One single batched `model.encode()` call on all N*window_len
    strings — same shape as the original implementation, kept this way
    so existing tests + the small-call paths in `ml.embedder.embed_window`
    don't suddenly observe two encode calls instead of one. The only
    behavioural change vs the pre-Task-1 version is `show_progress_bar=True`
    (the visible-progress fix).

    For full-corpus production embeddings, call `embed_or_load` — that
    path adds on-disk memmap'd checkpointing + resume support.
    """
    if not windows:
        return np.empty((0, 0, 0), dtype=np.float32)

    window_len = len(windows[0].templates)
    if any(len(w.templates) != window_len for w in windows):
        raise ValueError("all windows must have the same number of templates")

    flat_texts: list[str] = []
    for w in windows:
        flat_texts.extend(w.templates)

    flat_emb = np.asarray(
        model.encode(
            flat_texts,
            batch_size=batch_size,
            normalize_embeddings=True,
            show_progress_bar=True,
        ),
        dtype=np.float32,
    )
    if flat_emb.ndim != 2:
        raise RuntimeError(f"embedder returned ndim={flat_emb.ndim}, expected 2")
    if flat_emb.shape[0] != len(windows) * window_len:
        raise RuntimeError(
            f"embedder returned {flat_emb.shape[0]} vectors, "
            f"expected {len(windows) * window_len}"
        )

    return flat_emb.reshape(len(windows), window_len, flat_emb.shape[1])


def _embed_into(
    out: np.ndarray,
    windows: list[Window],
    *,
    model: SBertLike,
    batch_size: int,
    start_chunk: int,
    progress_path: Path | None,
) -> None:
    """Embed `windows` chunk-by-chunk, writing into `out[i, j, k]`.

    `out` may be a regular ndarray or a `np.lib.format.open_memmap`
    handle — either way, in-place writes are flushed each chunk so
    a kill at any point leaves a recoverable partial state.

    `progress_path` (if given) holds an integer = next chunk to embed.
    Each completed chunk increments it. Cleared by the caller on full
    completion.
    """
    n = out.shape[0]
    window_len = out.shape[1]
    n_chunks = (n + CHUNK_WINDOWS - 1) // CHUNK_WINDOWS
    print(
        f"[embed] {n:,} windows × {window_len} templates × {out.shape[2]}D, "
        f"{n_chunks} chunks of up to {CHUNK_WINDOWS:,} windows each"
    )
    if start_chunk > 0:
        print(f"[embed] resuming from chunk {start_chunk}/{n_chunks}")

    t_run = time.monotonic()
    for chunk_idx in range(start_chunk, n_chunks):
        chunk_t0 = time.monotonic()
        start = chunk_idx * CHUNK_WINDOWS
        end = min(start + CHUNK_WINDOWS, n)
        chunk = windows[start:end]

        flat_texts: list[str] = []
        for w in chunk:
            flat_texts.extend(w.templates)

        flat_emb = np.asarray(
            model.encode(
                flat_texts,
                batch_size=batch_size,
                normalize_embeddings=True,
                show_progress_bar=True,
            ),
            dtype=np.float32,
        )
        if flat_emb.shape[0] != (end - start) * window_len:
            raise RuntimeError(
                f"embedder returned {flat_emb.shape[0]} vectors, "
                f"expected {(end - start) * window_len}"
            )
        out[start:end] = flat_emb.reshape(end - start, window_len, out.shape[2])

        # Persist progress so a kill mid-loop is recoverable.
        if hasattr(out, "flush"):
            out.flush()  # type: ignore[attr-defined]
        if progress_path is not None:
            progress_path.write_text(str(chunk_idx + 1))

        chunks_done = chunk_idx + 1 - start_chunk
        avg_per_chunk = (time.monotonic() - t_run) / max(chunks_done, 1)
        eta_min = (n_chunks - chunk_idx - 1) * avg_per_chunk / 60.0
        chunk_dt = time.monotonic() - chunk_t0
        print(
            f"[embed] chunk {chunk_idx + 1}/{n_chunks} — "
            f"{end - start:,} windows in {chunk_dt:.1f}s "
            f"(ETA {eta_min:.1f} min)"
        )


# -- Caching layer (the iteration-loop saver) -----------------------------

def _progress_path_for(cache_path: Path) -> Path:
    """Sidecar file: integer count of completed chunks."""
    return cache_path.with_suffix(cache_path.suffix + ".progress")


def _read_progress(progress_path: Path) -> int:
    try:
        return int(progress_path.read_text().strip())
    except (FileNotFoundError, ValueError):
        return 0


def cache_embeddings(emb: np.ndarray, dest: Path) -> None:
    """Save embeddings to `.npy`, creating parent dirs. Idempotent.

    Kept for back-compat with callers that build embeddings in memory
    and just want them written. The chunked path in `embed_or_load`
    bypasses this — it writes through a memmap directly.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    np.save(dest, emb)


def load_cached_embeddings(src: Path) -> np.ndarray | None:
    """Return cached embeddings if present and non-empty, else None.

    Refuses to return data while a `.progress` sidecar exists — that
    indicates a partial cache from a killed run. Callers should pass
    `resume=True` to `embed_or_load` to continue, or delete the sidecar
    to start over.
    """
    if not src.exists():
        return None
    if _progress_path_for(src).exists():
        return None  # partial cache — caller decides whether to resume
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
    resume: bool = False,
) -> np.ndarray:
    """Top-level entry point: load `cache_path` if complete, else embed.

    Embedding writes through a `np.lib.format.open_memmap` so the
    process's working set stays bounded even on the full 11 M-line HDFS
    corpus. A `.progress` sidecar tracks the next chunk to embed; pass
    `resume=True` to continue from there after a kill.

    Args:
        rebuild: ignore any cache (full or partial) and start fresh.
        resume:  if a `.progress` sidecar exists alongside `cache_path`,
                 pick up from that chunk instead of re-embedding from 0.
                 Mutually exclusive with `rebuild`.
    """
    if rebuild and resume:
        raise ValueError("`rebuild=True` and `resume=True` are mutually exclusive")

    progress_path = _progress_path_for(cache_path)

    # Fast path: complete, valid cache.
    if not rebuild:
        cached = load_cached_embeddings(cache_path)
        if cached is not None and cached.shape[0] == len(windows):
            print(f"[skip] using cached embeddings: {cache_path} {cached.shape}")
            return cached

    if not windows:
        empty = np.empty((0, 0, 0), dtype=np.float32)
        cache_embeddings(empty, cache_path)
        progress_path.unlink(missing_ok=True)
        return empty

    window_len = len(windows[0].templates)
    if any(len(w.templates) != window_len for w in windows):
        raise ValueError("all windows must have the same number of templates")

    # Decide where to resume from. Resume only if requested AND a partial
    # cache with the right shape already exists.
    start_chunk = 0
    if resume and cache_path.exists() and progress_path.exists():
        try:
            existing = np.lib.format.open_memmap(cache_path, mode="r")
            if existing.shape[0] == len(windows) and existing.shape[1] == window_len:
                start_chunk = _read_progress(progress_path)
                dim = existing.shape[2]
                del existing
                print(
                    f"[embed] --resume: reusing partial cache, "
                    f"continuing from chunk {start_chunk}"
                )
            else:
                print(
                    f"[embed] --resume: shape mismatch "
                    f"(cache {existing.shape} vs needed ({len(windows)}, {window_len}, *)) "
                    "— starting fresh"
                )
                del existing
                start_chunk = 0
        except (ValueError, OSError) as e:
            print(f"[embed] --resume: partial cache unreadable ({e}) — starting fresh")
            start_chunk = 0

    # Fresh start: embed the first chunk, derive dim from that result,
    # allocate the memmap, copy chunk 0 into it, then continue from
    # chunk 1. Folding the dim discovery into chunk 0 keeps the test
    # invariant "small data = exactly N encode calls per chunk" intact
    # — a separate probe call would push the count to N+1.
    if start_chunk == 0:
        if cache_path.exists():
            cache_path.unlink()
        progress_path.unlink(missing_ok=True)

        first_chunk_size = min(CHUNK_WINDOWS, len(windows))
        first_chunk = windows[:first_chunk_size]
        first_flat: list[str] = []
        for w in first_chunk:
            first_flat.extend(w.templates)
        first_emb = np.asarray(
            model.encode(
                first_flat,
                batch_size=batch_size,
                normalize_embeddings=True,
                show_progress_bar=True,
            ),
            dtype=np.float32,
        )
        if first_emb.ndim != 2:
            raise RuntimeError(
                f"embedder returned ndim={first_emb.ndim}, expected 2"
            )
        if first_emb.shape[0] != first_chunk_size * window_len:
            raise RuntimeError(
                f"embedder returned {first_emb.shape[0]} vectors, "
                f"expected {first_chunk_size * window_len}"
            )
        dim = first_emb.shape[-1]

        cache_path.parent.mkdir(parents=True, exist_ok=True)
        out = np.lib.format.open_memmap(
            cache_path, mode="w+", dtype=np.float32,
            shape=(len(windows), window_len, dim),
        )
        out[:first_chunk_size] = first_emb.reshape(
            first_chunk_size, window_len, dim,
        )
        if hasattr(out, "flush"):
            out.flush()  # type: ignore[attr-defined]
        progress_path.write_text("1")
        n_chunks_total = (len(windows) + CHUNK_WINDOWS - 1) // CHUNK_WINDOWS
        print(
            f"[embed] {len(windows):,} windows × {window_len} templates × {dim}D, "
            f"{n_chunks_total} chunks of up to {CHUNK_WINDOWS:,} windows each"
        )
        # Continue from chunk 1; chunk 0 already written.
        start_chunk = 1
    else:
        out = np.lib.format.open_memmap(cache_path, mode="r+")

    # _embed_into is a no-op when start_chunk >= n_chunks (all done).
    _embed_into(
        out, windows,
        model=model, batch_size=batch_size,
        start_chunk=start_chunk, progress_path=progress_path,
    )

    # Mark the cache as complete: drop the progress sidecar so future
    # `load_cached_embeddings` calls return the data without resume.
    progress_path.unlink(missing_ok=True)

    print(f"[embed] saved {cache_path} {out.shape}")
    # Return a regular ndarray view rather than the live memmap so
    # callers can mutate without touching disk.
    return np.asarray(out)


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
