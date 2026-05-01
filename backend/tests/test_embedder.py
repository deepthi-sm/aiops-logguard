"""
Tests for `ml.embedder` — the live SBERT wrapper.

Uses a stub `SBertLike` so we don't pull the 80 MB sentence-transformers
weights during CI. The contract being tested is "live and training take
the same code path"; the actual embedding quality is exercised by
training-side tests against the real model.
"""
import numpy as np

from ml import embedder as live
from training import embed as train_embed
from training.sequence_builder import ParsedLog, build_windows


class _StubSbert:
    """Returns a predictable per-template embedding so we can assert the
    embedder fed the right strings to encode() in the right order."""

    def __init__(self, dim: int = 8) -> None:
        self.dim = dim
        self.calls: list[list[str]] = []

    def encode(
        self,
        sentences,
        batch_size: int = 64,
        normalize_embeddings: bool = True,
        show_progress_bar: bool = False,
    ) -> np.ndarray:
        self.calls.append(list(sentences))
        # Deterministic embedding: fingerprint each sentence by hash so two
        # equal strings produce identical vectors.
        out = np.zeros((len(sentences), self.dim), dtype=np.float32)
        for i, s in enumerate(sentences):
            h = abs(hash(s)) % 10_000
            out[i] = (np.arange(self.dim) + h) % 7
        return out


def _events(n: int) -> list[ParsedLog]:
    return [
        ParsedLog(
            raw=f"line {i}",
            template=f"template_{i % 5}",
            template_id=str(i % 5),
            source="host-1",
            line_no=i,
        )
        for i in range(n)
    ]


def test_embed_window_returns_per_event_embedding():
    window = build_windows(_events(20))[0]
    stub = _StubSbert(dim=8)

    emb = live.embed_window(window, model=stub)

    assert emb.shape == (20, 8)
    assert emb.dtype == np.float32
    # Stub got called once with all 20 templates in order.
    assert len(stub.calls) == 1
    assert stub.calls[0] == window.templates


def test_embed_window_reuses_training_implementation():
    """Live `embed_window` must produce the identical numbers as the
    training-side `embed_windows([window])[0]` for the same input."""
    window = build_windows(_events(20))[0]
    stub_a = _StubSbert(dim=8)
    stub_b = _StubSbert(dim=8)

    live_emb = live.embed_window(window, model=stub_a)
    train_emb = train_embed.embed_windows([window], model=stub_b)[0]

    assert np.array_equal(live_emb, train_emb)


def test_sbert_protocol_re_exported():
    """The Protocol used to type the model parameter must be the SAME
    object as training's, so a single mock satisfies both paths."""
    assert live.SBertLike is train_embed.SBertLike
