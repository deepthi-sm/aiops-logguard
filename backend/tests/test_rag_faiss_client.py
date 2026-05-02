"""
Tests for `rag.faiss_client.FaissClient`.

Builds a tiny in-memory IndexFlatIP at test time so we don't depend on
the gitignored `artifacts/faiss.index`.
"""
from __future__ import annotations

import faiss
import numpy as np
import pytest

from rag.faiss_client import FaissClient
from training.build_faiss import IncidentRecord


def _records(n: int) -> list[IncidentRecord]:
    return [
        IncidentRecord(
            incident_id=f"syn_{i:03d}",
            template=f"ERROR template_{i}",
            root_cause=f"cause for incident {i}",
            recommended_fix=f"fix for {i}",
            resolved_at=None,
            source="synthetic",
        )
        for i in range(n)
    ]


def _index_with_unit_vectors(n: int, dim: int = 8) -> faiss.Index:
    """Build an IndexFlatIP whose row i is the i-th canonical basis
    vector, so a query of e_i returns row i first with similarity 1.0."""
    vecs = np.eye(n, dim, dtype=np.float32)
    index = faiss.IndexFlatIP(dim)
    index.add(vecs)
    return index


# -- construction ---------------------------------------------------------


def test_size_mismatch_rejected():
    """Constructor refuses if records and index disagree on length."""
    index = _index_with_unit_vectors(3)
    with pytest.raises(ValueError, match="size mismatch"):
        FaissClient(index, _records(4))


def test_size_and_dim_properties():
    index = _index_with_unit_vectors(5, dim=8)
    client = FaissClient(index, _records(5))
    assert client.size == 5
    assert client.dim == 8


# -- query ----------------------------------------------------------------


class TestQuery:
    def test_top_k_returns_nearest_first(self):
        client = FaissClient(_index_with_unit_vectors(5, 8), _records(5))
        # Query e_2 — should return row 2 first with similarity 1.0
        q = np.zeros(8, dtype=np.float32)
        q[2] = 1.0
        hits = client.query(q, k=3)
        assert len(hits) == 3
        assert hits[0].record.incident_id == "syn_002"
        assert hits[0].similarity == pytest.approx(1.0, abs=1e-5)
        # Other rows are orthogonal → similarity ~ 0
        for h in hits[1:]:
            assert h.similarity == pytest.approx(0.0, abs=1e-5)

    def test_two_d_query_accepted(self):
        client = FaissClient(_index_with_unit_vectors(5, 8), _records(5))
        q = np.zeros((1, 8), dtype=np.float32)
        q[0, 1] = 1.0
        hits = client.query(q, k=1)
        assert hits[0].record.incident_id == "syn_001"

    def test_k_larger_than_index_returns_all(self):
        client = FaissClient(_index_with_unit_vectors(3, 8), _records(3))
        hits = client.query(np.zeros(8, dtype=np.float32), k=10)
        assert len(hits) == 3

    def test_empty_index_returns_empty(self):
        empty = faiss.IndexFlatIP(8)
        client = FaissClient(empty, [])
        assert client.query(np.zeros(8, dtype=np.float32), k=3) == []

    def test_wrong_dim_query_rejected(self):
        client = FaissClient(_index_with_unit_vectors(5, 8), _records(5))
        with pytest.raises(ValueError, match="query dim"):
            client.query(np.zeros(7, dtype=np.float32), k=1)

    def test_higher_rank_query_rejected(self):
        client = FaissClient(_index_with_unit_vectors(5, 8), _records(5))
        with pytest.raises(ValueError, match="expected"):
            client.query(np.zeros((2, 8), dtype=np.float32), k=1)
