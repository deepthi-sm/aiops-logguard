"""
Tests for `rag.explainer.RagExplainer`.

Strategy: stub the four external dependencies — Postgres pool, Redis
subscriber, SBERT embedder, FAISS client, LLaMA client — so the
worker's wiring is exercised without spinning up real services. The
end-to-end "actually generate an explanation" flow is covered against
a real Ollama by a manual smoke test (see the explainer's CLI).
"""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

import faiss
import numpy as np
import pytest

from api.schemas import Anomaly, ContributingLine
from rag.explainer import RagExplainer, _to_similar_incidents
from rag.faiss_client import FaissClient, RetrievedIncident
from training.build_faiss import IncidentRecord

# -- stubs ----------------------------------------------------------------


class _StubEmbedder:
    """Returns a deterministic vector for any input."""

    def __init__(self, dim: int = 8) -> None:
        self.dim = dim
        self.calls: list[list[str]] = []

    def encode(
        self,
        sentences,
        batch_size: int = 1,
        normalize_embeddings: bool = True,
        show_progress_bar: bool = False,
    ) -> np.ndarray:
        self.calls.append(list(sentences))
        # Return e_2 so retrieval is predictable against a unit-vector
        # FAISS index built below.
        out = np.zeros((len(sentences), self.dim), dtype=np.float32)
        out[:, 2] = 1.0
        return out


class _StubLlama:
    """Records the system + user prompts and returns a canned canonical
    two-section response that the parser can split."""
    model = "stub-llama"

    def __init__(self, response: str | None = None) -> None:
        self.calls: list[tuple[str, str]] = []
        self._response = response or (
            "ROOT CAUSE:\n"
            "Stub root cause text for the test.\n\n"
            "RECOMMENDED FIX:\n"
            "1. Stubbed step one.\n"
            "2. Stubbed step two."
        )

    async def generate(
        self, *, system: str, user: str, request_id: str | None = None,
    ) -> str:
        self.calls.append((system, user))
        return self._response

    async def aclose(self) -> None:
        pass


class _RaisingLlama:
    """For the failure-path test."""
    model = "broken"

    async def generate(
        self, *, system: str, user: str, request_id: str | None = None,
    ) -> str:
        raise RuntimeError("Ollama is offline")

    async def aclose(self) -> None:
        pass


class _StubSubscriber:
    """Doesn't matter for the per-message tests — we never call run()."""

    async def aclose(self) -> None:
        pass

    def pubsub(self):
        raise NotImplementedError("Not used in per-message tests")


class _CapturingPool:
    """Lets us patch repository.get_anomaly + update_explanation around
    a sentinel pool instance — actual queries happen via patched
    functions, not the pool."""


# -- helpers --------------------------------------------------------------


def _faiss_unit_vectors(n: int, dim: int = 8) -> FaissClient:
    """Tiny in-memory FAISS index where row i = canonical basis e_i."""
    vecs = np.eye(n, dim, dtype=np.float32)
    index = faiss.IndexFlatIP(dim)
    index.add(vecs)
    records = [
        IncidentRecord(
            incident_id=f"syn_{i:03d}",
            template=f"ERROR template_{i}",
            root_cause=f"cause for {i}",
            recommended_fix=f"fix for {i}",
            resolved_at=None,
            source="synthetic",
        )
        for i in range(n)
    ]
    return FaissClient(index, records)


def _anomaly(anomaly_id: str = "anom_x") -> Anomaly:
    return Anomaly(
        id=anomaly_id,
        detected_at=datetime(2026, 5, 1, 12, 0, tzinfo=UTC),
        severity="warning",
        source="nova-api-prod-3",
        ensemble_score=0.85,
        confidence=0.7,
        failure_probability=0.6,
        predicted_failure_window_min=None,
        log_template="ERROR keystone-api auth failed",
        sequence_preview=["INFO line", "ERROR keystone-api auth failed"],
        top_contributing_lines=[
            ContributingLine(line="ERROR keystone-api auth failed", attention=0.5),
        ],
        explanation_status="pending",
        cluster_id="clu_a",
        cluster_size=1,
    )


# -- _to_similar_incidents -------------------------------------------------


def test_to_similar_incidents_clamps_similarity():
    """FAISS IP can drift outside [0, 1] from float-precision noise.
    Pydantic schema requires similarity_score ∈ [0, 1]. Clamp."""
    hits = [
        RetrievedIncident(
            record=IncidentRecord(
                incident_id="syn_001", template="t", root_cause="c",
                recommended_fix="f", resolved_at=None, source="synthetic",
            ),
            similarity=1.0001,
        ),
        RetrievedIncident(
            record=IncidentRecord(
                incident_id="syn_002", template="t", root_cause="c",
                recommended_fix="f", resolved_at=None, source="synthetic",
            ),
            similarity=-0.05,
        ),
    ]
    out = _to_similar_incidents(hits)
    assert out[0].similarity_score == 1.0
    assert out[1].similarity_score == 0.0


# -- per-message handler --------------------------------------------------


class TestHandleOne:
    @pytest.mark.asyncio
    async def test_happy_path_writes_ready_explanation(self, monkeypatch):
        """End-to-end on _handle_one: fetch anomaly → embed → retrieve
        → prompt → parse → write."""
        embedder = _StubEmbedder()
        llama = _StubLlama()
        faiss_c = _faiss_unit_vectors(5)

        # Stub out the repository functions so the test doesn't need a
        # real Postgres pool.
        async def fake_get(_pool, anomaly_id):
            assert anomaly_id == "anom_x"
            return _anomaly()

        update_calls: list[dict[str, Any]] = []

        async def fake_update(_pool, anomaly_id, **kwargs):
            update_calls.append({"id": anomaly_id, **kwargs})
            return True

        monkeypatch.setattr("rag.explainer.repository.get_anomaly", fake_get)
        monkeypatch.setattr(
            "rag.explainer.repository.update_explanation", fake_update,
        )

        explainer = RagExplainer(
            pool=_CapturingPool(),  # type: ignore[arg-type]
            subscriber=_StubSubscriber(),  # type: ignore[arg-type]
            embedder_model=embedder,
            faiss=faiss_c,
            llama=llama,
            top_k=3,
        )
        await explainer._handle_one("anom_x")

        # Embedder called with the anomaly's log template
        assert embedder.calls == [["ERROR keystone-api auth failed"]]

        # LLaMA called once with both prompts
        assert len(llama.calls) == 1
        sys_prompt, user_prompt = llama.calls[0]
        assert "site-reliability" in sys_prompt
        assert "ERROR keystone-api auth failed" in user_prompt
        assert "nova-api-prod-3" in user_prompt

        # update_explanation called with status='ready' and parsed sections
        assert len(update_calls) == 1
        call = update_calls[0]
        assert call["id"] == "anom_x"
        assert call["status"] == "ready"
        assert "Stub root cause text" in call["root_cause"]
        assert "Stubbed step one" in call["recommended_fix"]
        assert len(call["similar_incidents"]) == 3  # top_k=3

        assert explainer.stats.explained == 1
        assert explainer.stats.failed == 0
        assert explainer.stats.not_found == 0

    @pytest.mark.asyncio
    async def test_anomaly_not_in_db_increments_not_found(self, monkeypatch):
        async def fake_get(_pool, anomaly_id):
            return None  # row missing

        update_calls = []

        async def fake_update(_pool, anomaly_id, **kwargs):
            update_calls.append({"id": anomaly_id, **kwargs})
            return True

        monkeypatch.setattr("rag.explainer.repository.get_anomaly", fake_get)
        monkeypatch.setattr(
            "rag.explainer.repository.update_explanation", fake_update,
        )

        explainer = RagExplainer(
            pool=_CapturingPool(),  # type: ignore[arg-type]
            subscriber=_StubSubscriber(),  # type: ignore[arg-type]
            embedder_model=_StubEmbedder(),
            faiss=_faiss_unit_vectors(3),
            llama=_StubLlama(),
        )
        await explainer._handle_one("anom_missing")

        assert explainer.stats.not_found == 1
        assert explainer.stats.explained == 0
        assert update_calls == []  # nothing written

    @pytest.mark.asyncio
    async def test_ollama_failure_marks_row_failed(self, monkeypatch):
        """If LLaMA throws, the worker marks the row as 'failed' so the
        UI doesn't spin forever. The exception is caught at the loop
        level — _handle_one re-raises, and run() catches it.

        The dispatch path is now DB-poll based via `_next_pending_lifo`
        (was pubsub via `_iter_ids` before the LIFO + priority-queue
        rework). We monkey-patch that to deliver one anomaly id then
        return None, and bound the loop with `asyncio.wait_for` since
        run() is otherwise infinite (sleeps on empty queue).
        """
        async def fake_get(_pool, anomaly_id):
            return _anomaly()

        update_calls = []

        async def fake_update(_pool, anomaly_id, **kwargs):
            update_calls.append({"id": anomaly_id, **kwargs})
            return True

        monkeypatch.setattr("rag.explainer.repository.get_anomaly", fake_get)
        monkeypatch.setattr(
            "rag.explainer.repository.update_explanation", fake_update,
        )

        explainer = RagExplainer(
            pool=_CapturingPool(),  # type: ignore[arg-type]
            subscriber=_StubSubscriber(),  # type: ignore[arg-type]
            embedder_model=_StubEmbedder(),
            faiss=_faiss_unit_vectors(3),
            llama=_RaisingLlama(),
        )

        # Deliver one anomaly id, then drain. The loop sleeps 2s when
        # `_next_pending_lifo` returns None — wait_for cancels during
        # that sleep, which is the clean exit path.
        nexts: list[str | None] = ["anom_x"]

        async def fake_next() -> str | None:
            return nexts.pop(0) if nexts else None

        explainer._next_pending_lifo = fake_next  # type: ignore[assignment]

        try:
            await asyncio.wait_for(explainer.run(), timeout=0.5)
        except TimeoutError:
            pass

        assert explainer.stats.failed == 1
        # Best-effort: row marked as failed
        assert any(c["status"] == "failed" for c in update_calls)


# Ensure asyncio is reachable in test discovery (auto mode used).
_ = asyncio
