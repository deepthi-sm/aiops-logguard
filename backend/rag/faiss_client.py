"""
FAISS retrieval client for the RAG worker.

Wraps the artifacts produced by `training.build_faiss`:
  * `artifacts/faiss.index` — IndexFlatIP over 384-d unit-norm vectors
  * `artifacts/incidents.jsonl` — one IncidentRecord per row (same
    order as the FAISS row index)

Each query returns the top-K nearest IncidentRecords plus the inner-
product similarity score (the index is unit-norm so IP == cosine).
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import faiss
import numpy as np

from training.build_faiss import IncidentRecord, load_records

DEFAULT_INDEX_PATH = "artifacts/faiss.index"
DEFAULT_RECORDS_PATH = "artifacts/incidents.jsonl"
DEFAULT_TOP_K = 3


@dataclass(frozen=True)
class RetrievedIncident:
    """One row of the retrieval response.

    `similarity` is the FAISS inner-product score in [-1, 1] (unit-norm
    inputs → cosine similarity). Higher = more similar.
    """
    record: IncidentRecord
    similarity: float


class FaissClient:
    """Loads a FAISS index + parallel records file once and serves
    repeated nearest-neighbour queries.

    Construct via `FaissClient.from_artifacts(...)` for production.
    Tests use the constructor directly with a tiny in-memory index.
    """

    def __init__(
        self,
        index: faiss.Index,
        records: list[IncidentRecord],
    ) -> None:
        if index.ntotal != len(records):
            raise ValueError(
                f"index/records size mismatch: {index.ntotal} vs {len(records)}"
            )
        self._index = index
        self._records = records

    @classmethod
    def from_artifacts(
        cls,
        *,
        index_path: Path | str = DEFAULT_INDEX_PATH,
        records_path: Path | str = DEFAULT_RECORDS_PATH,
    ) -> FaissClient:
        index_path = Path(index_path)
        records_path = Path(records_path)
        if not index_path.exists():
            raise FileNotFoundError(f"FAISS index missing: {index_path}")
        if not records_path.exists():
            raise FileNotFoundError(f"incidents file missing: {records_path}")
        index = faiss.read_index(str(index_path))
        records = load_records(records_path)
        return cls(index, records)

    @property
    def size(self) -> int:
        return len(self._records)

    @property
    def dim(self) -> int:
        return int(self._index.d)

    def query(
        self,
        vector: np.ndarray,
        *,
        k: int = DEFAULT_TOP_K,
    ) -> list[RetrievedIncident]:
        """Return the top-K most similar incidents to `vector`.

        `vector` must be 1-D (single query) or 2-D `(1, dim)`. Caller is
        responsible for L2-normalising; if the vector isn't unit-norm,
        IP is no longer cosine and ranking degrades.
        """
        if vector.ndim == 1:
            vec = vector.reshape(1, -1).astype(np.float32)
        elif vector.ndim == 2 and vector.shape[0] == 1:
            vec = vector.astype(np.float32)
        else:
            raise ValueError(
                f"expected (dim,) or (1, dim); got shape {vector.shape}"
            )
        if vec.shape[1] != self.dim:
            raise ValueError(
                f"query dim {vec.shape[1]} != index dim {self.dim}"
            )

        k_eff = min(k, self.size)
        if k_eff == 0:
            return []
        sims, idx = self._index.search(vec, k_eff)
        out: list[RetrievedIncident] = []
        for sim, i in zip(sims[0].tolist(), idx[0].tolist(), strict=True):
            if i < 0:  # FAISS may return -1 when fewer matches exist
                continue
            out.append(RetrievedIncident(
                record=self._records[i],
                similarity=float(sim),
            ))
        return out
