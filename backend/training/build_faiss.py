"""
Build the FAISS index used by the RAG worker (Step 5).

For every new live anomaly, the RAG worker computes its embedding and looks
up the top-K most similar past incidents. Each match brings along its
metadata — template, root_cause, recommended_fix — which is fed to LLaMA
as context. Without this seeding, LLaMA produces vague output; with it,
even the very first detected anomaly gets a useful explanation.

The index combines two sources:

  1. **Real OpenStack training-set anomalies** — windows whose `labels == 1`.
     Their templates and embeddings provide the model-shaped similarity
     space.

  2. **Hand-written synthetic web-app incidents** — `synthetic_incidents.jsonl`.
     20 realistic backend-failure patterns (connection pool exhaustion, OOM,
     slow query, etc.) with rich root_cause + recommended_fix text. These
     are what make the RAG output useful from day one.

Output:

  * `artifacts/faiss.index` — FAISS IndexFlatIP over 384-d unit-norm vectors
  * `artifacts/incidents.jsonl` — metadata per index entry (same order as
                                  the index)

CLI:
    python -m training.build_faiss \\
        --embeddings artifacts/embeddings_openstack.npy \\
        --labels    artifacts/labels_openstack.npy \\
        --windows   artifacts/windows_openstack.jsonl \\
        --synthetic training/synthetic_incidents.jsonl
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import faiss
import numpy as np

# -- Index metadata schema -------------------------------------------------

@dataclass
class IncidentRecord:
    """One entry in `incidents.jsonl`. Order matches the FAISS row index."""
    incident_id: str
    template: str
    root_cause: str
    recommended_fix: str
    resolved_at: str | None
    source: str  # "training" | "synthetic"

    def to_dict(self) -> dict:
        return {
            "incident_id": self.incident_id,
            "template": self.template,
            "root_cause": self.root_cause,
            "recommended_fix": self.recommended_fix,
            "resolved_at": self.resolved_at,
            "source": self.source,
        }


# -- Synthetic incidents ---------------------------------------------------

def load_synthetic_incidents(path: Path) -> list[dict[str, Any]]:
    """Load 20+ hand-written backend-failure incidents from JSONL."""
    out = []
    with path.open("r", encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line:
                continue
            out.append(json.loads(line))
    return out


# -- Index building --------------------------------------------------------

def _normalise_l2(vectors: np.ndarray) -> np.ndarray:
    """Force unit-norm so IndexFlatIP behaves like cosine similarity."""
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    norms = np.maximum(norms, 1e-9)
    return (vectors / norms).astype(np.float32)


def build_index_from_training_anomalies(
    embeddings: np.ndarray,
    labels: np.ndarray,
    windows_meta: list[dict[str, Any]],
) -> tuple[np.ndarray, list[IncidentRecord]]:
    """Pick out windows where `labels == 1`, mean-pool their per-template
    vectors, and prepare them as index entries.

    `windows_meta[i]` is the metadata for window i (from the manifest written
    by the orchestrator) — used to recover the template string for the
    incident record.

    Returns `(vectors, records)` where vectors is (N, 384) unit-norm and
    records is the parallel metadata list.
    """
    if embeddings.shape[0] != labels.shape[0]:
        raise ValueError(
            f"embeddings/labels mismatch: {embeddings.shape[0]} vs {labels.shape[0]}"
        )
    if embeddings.shape[0] != len(windows_meta):
        raise ValueError(
            f"embeddings/windows_meta mismatch: {embeddings.shape[0]} vs {len(windows_meta)}"
        )

    anomaly_idx = np.where(labels == 1)[0]
    if len(anomaly_idx) == 0:
        return np.empty((0, embeddings.shape[2]), dtype=np.float32), []

    # Mean-pool the (N, 20, 384) → (N, 384) so each anomaly is one vector.
    pooled = embeddings[anomaly_idx].mean(axis=1)
    pooled = _normalise_l2(pooled)

    records: list[IncidentRecord] = []
    for i, src_idx in enumerate(anomaly_idx):
        meta = windows_meta[src_idx]
        records.append(IncidentRecord(
            incident_id=f"train_{i:06d}",
            template=str(meta.get("template_preview", "<unknown>")),
            root_cause="Anomaly observed in OpenStack training corpus.",
            recommended_fix="No human-written remediation available; "
                            "consult similar synthetic incidents.",
            resolved_at=None,
            source="training",
        ))

    return pooled, records


def build_index_from_synthetic(
    incidents: list[dict[str, Any]],
    *,
    embedder,  # SBertLike from training/embed.py — kept untyped to avoid the import
) -> tuple[np.ndarray, list[IncidentRecord]]:
    """Embed each synthetic incident's `template` and turn it into an index entry."""
    if not incidents:
        return np.empty((0, 0), dtype=np.float32), []

    texts = [inc["template"] for inc in incidents]
    raw = embedder.encode(
        texts, batch_size=64, normalize_embeddings=True, show_progress_bar=False,
    )
    vectors = np.asarray(raw, dtype=np.float32)
    if vectors.ndim != 2:
        raise RuntimeError(
            f"embedder returned ndim={vectors.ndim}, expected 2"
        )
    vectors = _normalise_l2(vectors)

    records: list[IncidentRecord] = []
    for inc in incidents:
        records.append(IncidentRecord(
            incident_id=str(inc["incident_id"]),
            template=str(inc["template"]),
            root_cause=str(inc["root_cause"]),
            recommended_fix=str(inc["recommended_fix"]),
            resolved_at=inc.get("resolved_at"),
            source="synthetic",
        ))
    return vectors, records


def build_full_index(
    *,
    training_vectors: np.ndarray,
    training_records: list[IncidentRecord],
    synthetic_vectors: np.ndarray,
    synthetic_records: list[IncidentRecord],
) -> tuple[faiss.Index, list[IncidentRecord]]:
    """Concatenate training and synthetic entries into one FAISS index."""
    parts = [v for v in (training_vectors, synthetic_vectors) if v.size]
    if not parts:
        raise ValueError("no vectors to index — both training and synthetic are empty")
    if any(p.shape[1] != parts[0].shape[1] for p in parts):
        raise ValueError("training and synthetic vectors have different dims")
    vectors = np.concatenate(parts, axis=0).astype(np.float32)

    dim = vectors.shape[1]
    index = faiss.IndexFlatIP(dim)
    index.add(vectors)

    records = list(training_records) + list(synthetic_records)
    if index.ntotal != len(records):
        raise RuntimeError(
            f"index has {index.ntotal} entries, expected {len(records)} records"
        )
    return index, records


# -- Persistence -----------------------------------------------------------

def save_index(index: faiss.Index, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    faiss.write_index(index, str(dest))


def save_records(records: list[IncidentRecord], dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    with dest.open("w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r.to_dict()) + "\n")


def load_records(src: Path) -> list[IncidentRecord]:
    out: list[IncidentRecord] = []
    with src.open("r", encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line:
                continue
            d = json.loads(line)
            out.append(IncidentRecord(
                incident_id=d["incident_id"],
                template=d["template"],
                root_cause=d["root_cause"],
                recommended_fix=d["recommended_fix"],
                resolved_at=d.get("resolved_at"),
                source=d.get("source", "training"),
            ))
    return out


# -- CLI -------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build the FAISS index from labelled anomalies + hand-written incidents.",
    )
    parser.add_argument("--embeddings", type=Path, required=True)
    parser.add_argument("--labels", type=Path, required=True)
    parser.add_argument("--windows", type=Path, required=True,
                        help="Window manifest JSONL (one record per window, in order).")
    parser.add_argument("--synthetic", type=Path,
                        default=Path("training/synthetic_incidents.jsonl"))
    parser.add_argument("--index-out", type=Path,
                        default=Path("artifacts/faiss.index"))
    parser.add_argument("--records-out", type=Path,
                        default=Path("artifacts/incidents.jsonl"))
    parser.add_argument("--sbert-model", default="all-MiniLM-L6-v2")
    args = parser.parse_args(argv)

    embeddings = np.load(args.embeddings)
    labels = np.load(args.labels)

    windows_meta: list[dict[str, Any]] = []
    with args.windows.open("r", encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if line:
                windows_meta.append(json.loads(line))

    train_vec, train_rec = build_index_from_training_anomalies(embeddings, labels, windows_meta)
    print(f"[faiss] {len(train_rec):,} training anomalies indexed")

    synthetic = load_synthetic_incidents(args.synthetic)
    print(f"[faiss] embedding {len(synthetic)} synthetic incidents with SBERT…")
    from sentence_transformers import SentenceTransformer
    sbert = SentenceTransformer(args.sbert_model)
    syn_vec, syn_rec = build_index_from_synthetic(synthetic, embedder=sbert)

    index, records = build_full_index(
        training_vectors=train_vec, training_records=train_rec,
        synthetic_vectors=syn_vec, synthetic_records=syn_rec,
    )
    save_index(index, args.index_out)
    save_records(records, args.records_out)
    print(f"[done] {args.index_out} ({index.ntotal} entries) | {args.records_out}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
