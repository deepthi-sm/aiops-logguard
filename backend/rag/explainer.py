r"""
Step 5 — RAG explainer worker.

Subscribes to the Redis pubsub channel `anomalies:detected` (which the
live runner publishes anomaly ids on), then for each id:

  1. fetch the anomaly row from Postgres
  2. embed its log_template via SBERT
  3. retrieve top-K similar prior incidents from FAISS
  4. build the LLaMA prompt (system + user) per `rag.prompts`
  5. call Ollama (LLaMA 3 8B by default), get back a two-section response
  6. parse the response into root_cause + recommended_fix
  7. write the explanation back to Postgres with
     `explanation_status='ready'`. On any failure, set 'failed' so the
     UI doesn't show a permanent spinner.

Runs as its own process (`python -m rag.explainer`), separate from
the live runner — same Docker image, different command. Both share the
Postgres DB and the Redis instance via env vars.

Every external dependency is constructor-injected so unit tests stub
them with fakes; `build_default_explainer()` is the production wiring
helper.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import asyncpg
import numpy as np
import redis.asyncio as redis_aio

from api import repository
from api.db import DB_URL_ENV, create_pool
from api.repository import install_jsonb_codec
from api.schemas import SimilarIncident
from ingestion.runner import CHANNEL_DETECTED
from ml.embedder import SBertLike, load_default_sbert
from rag.faiss_client import (
    DEFAULT_INDEX_PATH,
    DEFAULT_RECORDS_PATH,
    DEFAULT_TOP_K,
    FaissClient,
    RetrievedIncident,
)
from rag.llama_client import LlamaClientLike, OllamaClient
from rag.prompts import SYSTEM_PROMPT, build_user_prompt, parse_response

log = logging.getLogger(__name__)


@dataclass
class ExplainerStats:
    """Lightweight observability for the CLI summary on shutdown."""
    received: int = 0
    explained: int = 0
    failed: int = 0
    not_found: int = 0  # anomaly id arrived but no DB row


# -- the worker ------------------------------------------------------------


class RagExplainer:
    """End-to-end RAG explainer.

    Pure compose: takes already-built clients and a DB pool. The CLI
    helper `build_default_explainer()` wires the production
    versions of each dependency.

    On every message:
      try { explain → write ready row }
      except { write failed row + log }

    A single bad anomaly (FAISS oddity, Ollama timeout, malformed
    LLaMA output) MUST NOT poison the loop. Each is handled in
    `_handle_one()` and the loop continues.
    """

    def __init__(
        self,
        *,
        pool: asyncpg.Pool,
        subscriber: redis_aio.Redis,
        embedder_model: SBertLike,
        faiss: FaissClient,
        llama: LlamaClientLike,
        top_k: int = DEFAULT_TOP_K,
    ) -> None:
        self._pool = pool
        self._subscriber = subscriber
        self._embedder = embedder_model
        self._faiss = faiss
        self._llama = llama
        self._top_k = top_k
        self.stats = ExplainerStats()

    async def run(self) -> None:
        """Subscribe + dispatch loop."""
        async for anomaly_id in self._iter_ids():
            self.stats.received += 1
            try:
                await self._handle_one(anomaly_id)
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                log.exception("explainer: unhandled error on %s", anomaly_id)
                self.stats.failed += 1
                # Best-effort mark the row as failed so the UI doesn't
                # spin forever. Swallow secondary errors.
                try:
                    await self._mark_failed(anomaly_id)
                except Exception:  # noqa: BLE001
                    log.exception(
                        "explainer: failed to mark %s as failed", anomaly_id
                    )

    async def _iter_ids(self) -> AsyncIterator[str]:
        """Subscribe to the detected channel and yield anomaly ids."""
        pubsub = self._subscriber.pubsub()
        await pubsub.subscribe(CHANNEL_DETECTED)
        try:
            async for message in pubsub.listen():
                if message.get("type") != "message":
                    continue
                payload = message.get("data")
                if isinstance(payload, bytes | bytearray):
                    payload = payload.decode("utf-8", errors="replace")
                if not isinstance(payload, str) or not payload:
                    continue
                yield payload
        finally:
            try:
                await pubsub.unsubscribe(CHANNEL_DETECTED)
                await pubsub.aclose()
            except Exception:  # noqa: BLE001
                pass

    # -- per-message work --------------------------------------------------

    async def _handle_one(self, anomaly_id: str) -> None:
        anomaly = await repository.get_anomaly(self._pool, anomaly_id)
        if anomaly is None:
            log.warning("explainer: anomaly %s not in DB; skipping", anomaly_id)
            self.stats.not_found += 1
            return

        # 1. embed the anomaly's log template
        query_vec = self._embed_template(anomaly.log_template)

        # 2. retrieve top-K similar prior incidents from FAISS
        retrieved = self._faiss.query(query_vec, k=self._top_k)

        # 3. build the prompt
        user_prompt = build_user_prompt(
            log_template=anomaly.log_template,
            sequence_preview=list(anomaly.sequence_preview),
            source=anomaly.source,
            similar=retrieved,
        )

        # 4. call LLaMA
        raw = await self._llama.generate(system=SYSTEM_PROMPT, user=user_prompt)

        # 5. parse response
        parsed = parse_response(raw)

        # 6. write back to Postgres
        similar_for_db = _to_similar_incidents(retrieved)
        ok = await repository.update_explanation(
            self._pool, anomaly_id,
            root_cause=parsed.root_cause,
            recommended_fix=parsed.recommended_fix,
            similar_incidents=similar_for_db,
            status="ready",
        )
        if not ok:
            # Race — the row vanished between fetch and write. Rare; log + count.
            log.warning("explainer: update returned 0 rows for %s", anomaly_id)
            self.stats.not_found += 1
            return

        self.stats.explained += 1
        log.info(
            "explainer: %s ready (k=%d, model=%s)",
            anomaly_id, len(retrieved),
            getattr(self._llama, "model", "<unknown>"),
        )

    def _embed_template(self, template: str) -> np.ndarray:
        """SBERT-embed the single template string. Returns unit-norm
        (1, 384) — the embedder's `normalize_embeddings=True` already
        ensures this, but we re-normalise defensively in case a stub
        embedder doesn't."""
        out = self._embedder.encode(
            [template],
            batch_size=1,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        arr = np.asarray(out, dtype=np.float32)
        if arr.ndim != 2 or arr.shape[0] != 1:
            raise RuntimeError(
                f"embedder returned shape {arr.shape}, expected (1, dim)"
            )
        norms = np.linalg.norm(arr, axis=1, keepdims=True)
        norms = np.maximum(norms, 1e-9)
        return (arr / norms).astype(np.float32)

    async def _mark_failed(self, anomaly_id: str) -> None:
        await repository.update_explanation(
            self._pool, anomaly_id,
            root_cause="",
            recommended_fix="",
            similar_incidents=[],
            status="failed",
        )


# -- helpers ---------------------------------------------------------------


def _to_similar_incidents(retrieved: list[RetrievedIncident]) -> list[SimilarIncident]:
    """Project the FAISS hits into the API's SimilarIncident schema."""
    out: list[SimilarIncident] = []
    for hit in retrieved:
        out.append(SimilarIncident(
            incident_id=hit.record.incident_id,
            template=hit.record.template,
            resolved_at=_parse_resolved_at(hit.record.resolved_at),
            similarity_score=_clamp01(hit.similarity),
        ))
    return out


def _clamp01(x: float) -> float:
    """FAISS IP can be slightly outside [-1, 1] from float drift; the
    Pydantic schema requires [0, 1]. Negative similarity is also clipped
    to 0 because the schema is monotone-positive."""
    if x < 0.0:
        return 0.0
    if x > 1.0:
        return 1.0
    return x


def _parse_resolved_at(value: Any):
    """Handle the resolved_at value as it comes off the FAISS records
    file (which serialises it as a string or null)."""
    from datetime import datetime
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


# -- production wiring -----------------------------------------------------


@dataclass
class ExplainerResources:
    """Resources to close on shutdown (in this order)."""
    pool: asyncpg.Pool
    subscriber: redis_aio.Redis
    llama: LlamaClientLike
    others: list = field(default_factory=list)


async def build_default_explainer(
    *,
    redis_url: str | None = None,
    db_url: str | None = None,
    index_path: str | Path | None = None,
    records_path: str | Path | None = None,
    top_k: int = DEFAULT_TOP_K,
) -> tuple[RagExplainer, ExplainerResources]:
    """Wire up the production explainer from env vars / defaults.

    Returns the explainer + a resources bag the caller closes on
    shutdown. Failure to connect to any of (Redis, Postgres, FAISS,
    Ollama) raises here so the process exits early — better than
    silently consuming messages that we can't process."""
    redis_url = redis_url or os.environ.get(
        "LOGGUARD_REDIS_URL", "redis://localhost:6379"
    )
    db_url = db_url or os.environ.get(DB_URL_ENV)
    if not db_url:
        raise RuntimeError(
            f"{DB_URL_ENV} not set — RAG worker needs Postgres."
        )
    index_path = index_path or os.environ.get(
        "LOGGUARD_FAISS_INDEX", DEFAULT_INDEX_PATH
    )
    records_path = records_path or os.environ.get(
        "LOGGUARD_FAISS_RECORDS", DEFAULT_RECORDS_PATH
    )

    pool = await create_pool(db_url)
    async with pool.acquire() as conn:
        await install_jsonb_codec(conn)

    subscriber = redis_aio.from_url(redis_url, decode_responses=True)
    await subscriber.ping()  # fail-fast on bad Redis

    embedder = load_default_sbert()
    faiss = FaissClient.from_artifacts(
        index_path=index_path, records_path=records_path,
    )
    llama = OllamaClient()
    if not await llama.ping():
        log.warning(
            "ollama at %s did not respond to /api/tags — continuing anyway",
            llama.base_url,
        )

    explainer = RagExplainer(
        pool=pool,
        subscriber=subscriber,
        embedder_model=embedder,
        faiss=faiss,
        llama=llama,
        top_k=top_k,
    )
    resources = ExplainerResources(pool=pool, subscriber=subscriber, llama=llama)
    return explainer, resources


async def _close_all(res: ExplainerResources) -> None:
    try:
        await res.pool.close()
    except Exception:  # noqa: BLE001
        log.exception("close pool failed")
    try:
        await res.subscriber.aclose()
    except Exception:  # noqa: BLE001
        log.exception("close subscriber failed")
    try:
        await res.llama.aclose()
    except Exception:  # noqa: BLE001
        log.exception("close llama failed")


async def _run_cli() -> int:  # pragma: no cover — interactive runner
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
    )
    log.info("rag explainer: starting")
    explainer, resources = await build_default_explainer()
    log.info(
        "rag explainer: ready (faiss=%d entries, model=%s)",
        explainer._faiss.size,  # noqa: SLF001
        getattr(explainer._llama, "model", "<unknown>"),  # noqa: SLF001
    )
    try:
        await explainer.run()
    except asyncio.CancelledError:
        log.info("rag explainer: cancelled, shutting down")
    finally:
        await _close_all(resources)
        log.info(
            "rag explainer: stopped. received=%d explained=%d failed=%d not_found=%d",
            explainer.stats.received,
            explainer.stats.explained,
            explainer.stats.failed,
            explainer.stats.not_found,
        )
    return 0


# Pin import to avoid an "unused import" lint when explainer wraps the
# Anomaly schema indirectly via repository.get_anomaly. The schema is
# the data contract the worker writes to Postgres against.
_ = json


if __name__ == "__main__":  # pragma: no cover
    sys.exit(asyncio.run(_run_cli()))
