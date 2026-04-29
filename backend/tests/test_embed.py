"""
Tests for training/embed.py — SBERT batched embedding + caching.

A `FakeSBert` stand-in produces deterministic vectors so we can assert exact
shapes and round-trip through the cache without downloading the real
80 MB SBERT weights every test run.
"""
from pathlib import Path

import numpy as np
import pytest

from training.embed import (
    cache_embeddings,
    embed_or_load,
    embed_windows,
    load_cached_embeddings,
)
from training.sequence_builder import ParsedLog, build_windows


class FakeSBert:
    """Deterministic mock of SentenceTransformer for tests.

    Returns a 384-d vector per input, derived from `hash(text)` so two calls
    with the same string yield the same vector. Records every encode() call
    so tests can assert batching behaviour.
    """

    DIM = 384

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def encode(
        self,
        sentences: list[str],
        batch_size: int = 64,
        normalize_embeddings: bool = True,
        show_progress_bar: bool = False,
    ) -> np.ndarray:
        self.calls.append(
            {
                "n": len(sentences),
                "batch_size": batch_size,
                "normalize": normalize_embeddings,
            }
        )
        out = np.zeros((len(sentences), self.DIM), dtype=np.float32)
        for i, s in enumerate(sentences):
            rng = np.random.default_rng(seed=hash(s) & 0xFFFF_FFFF)
            v = rng.standard_normal(self.DIM).astype(np.float32)
            if normalize_embeddings:
                norm = np.linalg.norm(v)
                if norm > 0:
                    v = v / norm
            out[i] = v
        return out


def _make_windows(n: int, window_len: int = 20) -> list:
    events = [
        ParsedLog(
            raw=f"line {i}",
            template=f"template_{i % 5}",
            template_id=str(i % 5),
            source="openstack",
            line_no=i,
        )
        for i in range(n + window_len - 1)
    ]
    return build_windows(events, size=window_len)


# -- embed_windows ----------------------------------------------------------

class TestEmbedWindows:
    def test_returns_correct_shape(self):
        windows = _make_windows(3)
        emb = embed_windows(windows, model=FakeSBert())
        assert emb.shape == (3, 20, FakeSBert.DIM)

    def test_dtype_is_float32(self):
        windows = _make_windows(2)
        emb = embed_windows(windows, model=FakeSBert())
        assert emb.dtype == np.float32

    def test_makes_a_single_batched_encode_call(self):
        """The whole point of the batched path: one encode() call, not N."""
        sbert = FakeSBert()
        windows = _make_windows(5)
        embed_windows(windows, model=sbert)
        assert len(sbert.calls) == 1
        # 5 windows × 20 templates each
        assert sbert.calls[0]["n"] == 100

    def test_passes_through_batch_size(self):
        sbert = FakeSBert()
        embed_windows(_make_windows(2), model=sbert, batch_size=64)
        assert sbert.calls[0]["batch_size"] == 64

    def test_requests_normalized_embeddings(self):
        """Cosine-similarity-friendly form is the contract — FAISS uses inner
        product on these and assumes unit norm."""
        sbert = FakeSBert()
        embed_windows(_make_windows(1), model=sbert)
        assert sbert.calls[0]["normalize"] is True

    def test_empty_input_returns_empty_array(self):
        emb = embed_windows([], model=FakeSBert())
        assert emb.size == 0

    def test_rejects_uneven_window_lengths(self):
        from training.sequence_builder import Window

        bad = [
            Window(
                window_id="a",
                templates=["x"] * 20,
                raw_lines=["x"] * 20,
                label="unknown",
                source="src",
                line_range=(0, 19),
            ),
            Window(
                window_id="b",
                templates=["x"] * 19,         # WRONG length
                raw_lines=["x"] * 19,
                label="unknown",
                source="src",
                line_range=(0, 18),
            ),
        ]
        with pytest.raises(ValueError, match=r"same number of templates"):
            embed_windows(bad, model=FakeSBert())


# -- caching ---------------------------------------------------------------

class TestCaching:
    def test_round_trip(self, tmp_path: Path):
        emb = np.random.randn(3, 20, 384).astype(np.float32)
        dest = tmp_path / "emb.npy"
        cache_embeddings(emb, dest)
        loaded = load_cached_embeddings(dest)
        assert loaded is not None
        np.testing.assert_array_equal(loaded, emb)

    def test_load_returns_none_when_missing(self, tmp_path: Path):
        assert load_cached_embeddings(tmp_path / "no_such.npy") is None

    def test_cache_creates_parent_dirs(self, tmp_path: Path):
        emb = np.random.randn(1, 20, 384).astype(np.float32)
        dest = tmp_path / "deep" / "nested" / "emb.npy"
        cache_embeddings(emb, dest)
        assert dest.exists()


# -- embed_or_load (orchestrator) ------------------------------------------

class TestEmbedOrLoad:
    def test_uses_cache_on_second_call(self, tmp_path: Path):
        sbert = FakeSBert()
        cache = tmp_path / "openstack.npy"
        windows = _make_windows(2)

        first = embed_or_load(windows, model=sbert, cache_path=cache)
        assert sbert.calls  # called once
        sbert.calls.clear()

        second = embed_or_load(windows, model=sbert, cache_path=cache)
        assert sbert.calls == []   # not called again
        np.testing.assert_array_equal(first, second)

    def test_rebuild_bypasses_cache(self, tmp_path: Path):
        sbert = FakeSBert()
        cache = tmp_path / "openstack.npy"
        windows = _make_windows(2)

        embed_or_load(windows, model=sbert, cache_path=cache)
        sbert.calls.clear()
        embed_or_load(windows, model=sbert, cache_path=cache, rebuild=True)
        assert len(sbert.calls) == 1
