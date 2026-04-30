"""
Tests for training/build_faiss.py — FAISS index over labelled anomalies +
hand-written synthetic incidents.
"""
from pathlib import Path

import faiss
import numpy as np
import pytest

from training.build_faiss import (
    IncidentRecord,
    build_full_index,
    build_index_from_synthetic,
    build_index_from_training_anomalies,
    load_records,
    load_synthetic_incidents,
    save_index,
    save_records,
)

# -- Fakes -----------------------------------------------------------------

class FakeSBert:
    """Deterministic mock — same DIM as the real all-MiniLM-L6-v2."""
    DIM = 384

    def encode(self, texts, batch_size=64, normalize_embeddings=True, show_progress_bar=False):
        out = np.zeros((len(texts), self.DIM), dtype=np.float32)
        for i, t in enumerate(texts):
            rng = np.random.default_rng(seed=hash(t) & 0xFFFF_FFFF)
            v = rng.standard_normal(self.DIM).astype(np.float32)
            n = np.linalg.norm(v)
            if n > 0 and normalize_embeddings:
                v = v / n
            out[i] = v
        return out


# -- load_synthetic_incidents ---------------------------------------------

class TestLoadSyntheticIncidents:
    def test_in_repo_file_loads_at_least_20_incidents(self):
        """Architecture doc requires 20–30 hand-written incidents."""
        path = Path(__file__).resolve().parent.parent / "training" / "synthetic_incidents.jsonl"
        if not path.exists():
            pytest.skip(f"synthetic_incidents.jsonl not found at {path}")
        incidents = load_synthetic_incidents(path)
        assert len(incidents) >= 20

    def test_each_incident_has_required_fields(self):
        path = Path(__file__).resolve().parent.parent / "training" / "synthetic_incidents.jsonl"
        if not path.exists():
            pytest.skip(f"synthetic_incidents.jsonl not found at {path}")
        incidents = load_synthetic_incidents(path)
        for inc in incidents:
            for field in ("incident_id", "template", "root_cause", "recommended_fix"):
                assert field in inc, f"missing {field} in {inc.get('incident_id')}"
                assert inc[field], f"empty {field} in {inc.get('incident_id')}"

    def test_skips_blank_lines(self, tmp_path: Path):
        f = tmp_path / "incs.jsonl"
        f.write_text(
            "\n"
            '{"incident_id": "x", "template": "t", "root_cause": "rc", "recommended_fix": "fix"}\n'
            "\n",
            encoding="utf-8",
        )
        out = load_synthetic_incidents(f)
        assert len(out) == 1


# -- build_index_from_training_anomalies ----------------------------------

class TestBuildFromTraining:
    def test_picks_only_anomaly_labelled_windows(self):
        n_total, dim = 10, 384
        embeddings = np.random.randn(n_total, 20, dim).astype(np.float32)
        labels = np.array([0, 1, 0, 1, 0, 0, 1, 0, 0, 0])
        meta = [{"template_preview": f"t_{i}"} for i in range(n_total)]
        vec, rec = build_index_from_training_anomalies(embeddings, labels, meta)
        assert vec.shape[0] == 3   # 3 ones in the labels
        assert len(rec) == 3
        assert all(r.source == "training" for r in rec)

    def test_returns_unit_norm_vectors(self):
        embeddings = np.random.randn(5, 20, 384).astype(np.float32)
        labels = np.ones(5, dtype=np.int64)
        meta = [{"template_preview": "x"} for _ in range(5)]
        vec, _ = build_index_from_training_anomalies(embeddings, labels, meta)
        norms = np.linalg.norm(vec, axis=1)
        assert np.allclose(norms, 1.0, atol=1e-5)

    def test_no_anomalies_returns_empty(self):
        embeddings = np.random.randn(3, 20, 384).astype(np.float32)
        labels = np.zeros(3, dtype=np.int64)
        meta = [{"template_preview": "x"} for _ in range(3)]
        vec, rec = build_index_from_training_anomalies(embeddings, labels, meta)
        assert len(rec) == 0
        assert vec.shape == (0, 384)


# -- build_index_from_synthetic -------------------------------------------

class TestBuildFromSynthetic:
    def test_embeds_each_template(self):
        sbert = FakeSBert()
        incidents = [
            {"incident_id": "syn_001", "template": "ERROR pool exhausted",
             "root_cause": "rc", "recommended_fix": "fix", "resolved_at": None},
            {"incident_id": "syn_002", "template": "ERROR OOM kill",
             "root_cause": "rc2", "recommended_fix": "fix2", "resolved_at": None},
        ]
        vec, rec = build_index_from_synthetic(incidents, embedder=sbert)
        assert vec.shape == (2, FakeSBert.DIM)
        assert len(rec) == 2
        assert all(r.source == "synthetic" for r in rec)
        assert rec[0].incident_id == "syn_001"

    def test_records_carry_metadata(self):
        sbert = FakeSBert()
        incidents = [{
            "incident_id": "x",
            "template": "t",
            "root_cause": "rc",
            "recommended_fix": "fix",
            "resolved_at": "2024-01-01T00:00:00Z",
        }]
        _, rec = build_index_from_synthetic(incidents, embedder=sbert)
        assert rec[0].root_cause == "rc"
        assert rec[0].recommended_fix == "fix"
        assert rec[0].resolved_at == "2024-01-01T00:00:00Z"

    def test_empty_input_returns_empty(self):
        sbert = FakeSBert()
        vec, rec = build_index_from_synthetic([], embedder=sbert)
        assert vec.size == 0
        assert rec == []


# -- build_full_index + save/load -----------------------------------------

class TestFullIndex:
    def test_concat_training_and_synthetic(self):
        t_vec = np.random.randn(3, 384).astype(np.float32)
        t_vec = t_vec / np.linalg.norm(t_vec, axis=1, keepdims=True)
        t_rec = [
            IncidentRecord(f"t_{i}", "tmp", "rc", "fix", None, "training")
            for i in range(3)
        ]
        s_vec = np.random.randn(2, 384).astype(np.float32)
        s_vec = s_vec / np.linalg.norm(s_vec, axis=1, keepdims=True)
        s_rec = [
            IncidentRecord(f"s_{i}", "tmp", "rc", "fix", None, "synthetic")
            for i in range(2)
        ]
        index, records = build_full_index(
            training_vectors=t_vec, training_records=t_rec,
            synthetic_vectors=s_vec, synthetic_records=s_rec,
        )
        assert index.ntotal == 5
        assert len(records) == 5
        # Training records come first
        assert records[0].source == "training"
        assert records[3].source == "synthetic"

    def test_handles_empty_training_set(self):
        s_vec = np.random.randn(2, 384).astype(np.float32)
        s_vec = s_vec / np.linalg.norm(s_vec, axis=1, keepdims=True)
        s_rec = [
            IncidentRecord("s_0", "tmp", "rc", "fix", None, "synthetic"),
            IncidentRecord("s_1", "tmp", "rc", "fix", None, "synthetic"),
        ]
        index, records = build_full_index(
            training_vectors=np.empty((0, 384), dtype=np.float32),
            training_records=[],
            synthetic_vectors=s_vec, synthetic_records=s_rec,
        )
        assert index.ntotal == 2

    def test_rejects_dim_mismatch(self):
        t_vec = np.random.randn(2, 256).astype(np.float32)
        s_vec = np.random.randn(2, 384).astype(np.float32)
        with pytest.raises(ValueError, match=r"different dims"):
            build_full_index(
                training_vectors=t_vec, training_records=[
                    IncidentRecord(f"t_{i}", "t", "rc", "f", None, "training") for i in range(2)
                ],
                synthetic_vectors=s_vec, synthetic_records=[
                    IncidentRecord(f"s_{i}", "t", "rc", "f", None, "synthetic") for i in range(2)
                ],
            )

    def test_save_and_query(self, tmp_path: Path):
        rng = np.random.default_rng(0)
        vec = rng.standard_normal((4, 384)).astype(np.float32)
        vec = vec / np.linalg.norm(vec, axis=1, keepdims=True)
        rec = [
            IncidentRecord(f"x_{i}", "t", "rc", "fix", None, "synthetic")
            for i in range(4)
        ]
        index, records = build_full_index(
            training_vectors=np.empty((0, 384), dtype=np.float32),
            training_records=[],
            synthetic_vectors=vec,
            synthetic_records=rec,
        )

        index_path = tmp_path / "faiss.index"
        records_path = tmp_path / "incidents.jsonl"
        save_index(index, index_path)
        save_records(records, records_path)

        # Reload + query: each entry should be its own nearest neighbour
        loaded_index = faiss.read_index(str(index_path))
        loaded_records = load_records(records_path)
        assert loaded_index.ntotal == 4
        assert len(loaded_records) == 4

        _distances, indices = loaded_index.search(vec, k=1)
        # Each query's top-1 should be itself
        assert (indices[:, 0] == np.arange(4)).all()

    def test_records_jsonl_round_trip(self, tmp_path: Path):
        rec = [
            IncidentRecord("x", "tmp", "rc", "fix", "2024-01-01T00:00:00Z", "synthetic"),
            IncidentRecord("y", "tmp2", "rc2", "fix2", None, "training"),
        ]
        dest = tmp_path / "incs.jsonl"
        save_records(rec, dest)
        loaded = load_records(dest)
        assert len(loaded) == 2
        assert loaded[0].incident_id == "x"
        assert loaded[0].resolved_at == "2024-01-01T00:00:00Z"
        assert loaded[1].resolved_at is None
