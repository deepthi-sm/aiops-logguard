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
import time
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
    cache_hits: int = 0      # served from precomputed cache (sub-second)
    cache_misses: int = 0    # fell through to live LLaMA


# -- precomputed-explanation cache ----------------------------------------


@dataclass
class _CacheEntry:
    """One precomputed explanation, keyed by SBERT embedding similarity."""
    embedding: np.ndarray  # (384,) float32, unit-norm
    template_pattern: str
    root_cause: str
    recommended_fix: str
    similar_incidents: list[SimilarIncident]


class ExplanationCache:
    """In-memory cache of precomputed explanations.

    Loaded once at worker startup from
    `backend/artifacts/precomputed_explanations.json`. The lookup is
    a cosine-similarity match against the anomaly's already-computed
    SBERT embedding — same vector the FAISS query uses, so the cache
    check costs O(N * 384) FLOPs where N ≈ 17. Sub-millisecond.

    When the max similarity ≥ `match_threshold` (default 0.85), the
    cached payload is returned and the worker skips FAISS + LLaMA.
    """

    def __init__(self, entries: list[_CacheEntry], match_threshold: float = 0.85):
        self._entries = entries
        self._threshold = match_threshold
        # Stack embeddings into a (N, 384) matrix for one matmul per lookup.
        if entries:
            self._matrix = np.stack([e.embedding for e in entries]).astype(np.float32)
        else:
            self._matrix = np.zeros((0, 384), dtype=np.float32)

    @property
    def size(self) -> int:
        return len(self._entries)

    @property
    def match_threshold(self) -> float:
        return self._threshold

    @classmethod
    def load(cls, path: Path | str) -> ExplanationCache | None:
        """Load from the precompute artifact. Returns None if the file
        is missing — caller should fall back to live LLaMA only."""
        p = Path(path)
        if not p.exists():
            log.info("cache: %s not found — operating without fast-path cache", p)
            return None
        try:
            payload = json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            log.exception("cache: failed to load %s: %s", p, e)
            return None

        entries: list[_CacheEntry] = []
        for raw in payload.get("entries", []):
            try:
                emb = np.asarray(raw["embedding"], dtype=np.float32)
                # Defensive re-normalisation — JSON round-trip can
                # introduce float precision drift.
                n = float(np.linalg.norm(emb))
                if n > 1e-9:
                    emb = (emb / n).astype(np.float32)
                similar = [
                    SimilarIncident(
                        incident_id=s["incident_id"],
                        template=s["template"],
                        resolved_at=s.get("resolved_at"),
                        similarity_score=float(s["similarity_score"]),
                    )
                    for s in raw.get("similar_incidents", [])
                ]
                entries.append(_CacheEntry(
                    embedding=emb,
                    template_pattern=raw["template_pattern"],
                    root_cause=raw["root_cause"],
                    recommended_fix=raw["recommended_fix"],
                    similar_incidents=similar,
                ))
            except (KeyError, TypeError, ValueError):
                log.exception("cache: skipping malformed entry")
                continue
        threshold = float(payload.get("match_threshold", 0.85))
        log.info(
            "cache: loaded %d entries from %s (match_threshold=%.2f)",
            len(entries), p, threshold,
        )
        return cls(entries, match_threshold=threshold)

    def lookup(self, query_emb: np.ndarray) -> tuple[_CacheEntry, float] | None:
        """Find the best-matching cache entry. Returns `(entry, score)`
        if the top match clears the threshold; None otherwise.

        `query_emb` should be unit-norm (384,) — same shape the
        explainer's `_embed_template` produces. Caller is responsible
        for that.
        """
        if not self._entries:
            return None
        q = query_emb.reshape(-1).astype(np.float32)
        # All entries are unit-norm; q is unit-norm; matmul = cosine.
        scores = self._matrix @ q
        best_idx = int(np.argmax(scores))
        best_score = float(scores[best_idx])
        if best_score >= self._threshold:
            return self._entries[best_idx], best_score
        return None

    def best_match(self, query_emb: np.ndarray) -> tuple[_CacheEntry, float] | None:
        """Closest entry regardless of threshold. Demo-grade safety net:
        even if `lookup()` rejects the match, the click path can still
        return a "loosely related" cached explanation rather than fall
        through to a multi-second LLaMA queue.

        Use sparingly — under healthy operation `lookup()` should hit;
        falling through to this method means SBERT cosine to every
        cached template was below threshold, which is a useful signal
        the cache may need new templates.

        Returns None only when the cache is empty.
        """
        if not self._entries:
            return None
        q = query_emb.reshape(-1).astype(np.float32)
        scores = self._matrix @ q
        best_idx = int(np.argmax(scores))
        return self._entries[best_idx], float(scores[best_idx])


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
        cache: ExplanationCache | None = None,
    ) -> None:
        self._pool = pool
        self._subscriber = subscriber
        self._embedder = embedder_model
        self._faiss = faiss
        self._llama = llama
        self._top_k = top_k
        # Optional fast-path cache. When the anomaly's log_template
        # SBERT-embeds within `cache.match_threshold` cosine of a
        # precomputed entry, we skip FAISS + LLaMA entirely and write
        # the cached payload to the DB. Cache miss → fall through to
        # the live RAG pipeline.
        self._cache = cache
        self.stats = ExplainerStats()

    async def run(self) -> None:
        """DB-poll dispatch loop. Pops the NEWEST pending anomaly each
        round (LIFO).

        Why not pubsub anymore: pubsub is FIFO from the publisher's
        perspective and offers no replay / backlog handling. With user
        uploads producing hundreds of anomalies in seconds, the user
        invariably clicks the most-recently-detected row in the
        dashboard list — which under FIFO sits at the back of the
        queue, behind hundreds of older items. LIFO matches user
        expectation: the row they're looking at gets explained first.

        The pubsub channel still exists (for future fan-out / multi-
        worker designs) but is currently unused.
        """
        idle_sleep_s = 2.0
        while True:
            anomaly_id = await self._next_pending_lifo()
            if anomaly_id is None:
                # Queue empty — back off briefly and retry.
                try:
                    await asyncio.sleep(idle_sleep_s)
                except asyncio.CancelledError:
                    raise
                continue

            self.stats.received += 1
            try:
                await self._handle_one(anomaly_id)
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                log.exception("explainer: unhandled error on %s", anomaly_id)
                self.stats.failed += 1
                # Best-effort mark the row as failed so the UI doesn't
                # spin forever AND so this same anomaly isn't re-popped
                # by `_next_pending_lifo` on the next loop iteration
                # (the WHERE filter is `status='pending'`).
                try:
                    await self._mark_failed(anomaly_id)
                except Exception:  # noqa: BLE001
                    log.exception(
                        "explainer: failed to mark %s as failed", anomaly_id
                    )

    async def _next_pending_lifo(self) -> str | None:
        """Next anomaly to explain. Priority set first, then LIFO DB poll.

        Selection order:
          1. `anomalies:priority:set` Redis SET — populated by the API
             when a user GETs /explanation on a pending anomaly. SET
             (not list) so the frontend's repeat polls collapse to one
             entry per anomaly.
          2. Newest `pending` row in the anomalies table — LIFO so the
             most-recently-detected anomaly (typically what the user
             is staring at on the dashboard) is processed before older
             entries from the same upload.

        SPOP returns a random member, which is fine for the demo: every
        member is "the user wanted this one" and order among them is
        functionally irrelevant. Random pop also avoids any single
        anomaly monopolising the queue if the frontend re-bumps
        aggressively.

        Single-worker assumption — no row-level locking. With multiple
        workers we'd want `FOR UPDATE SKIP LOCKED` on the DB query.
        """
        # 1. Priority set (user GET /explanation on a pending row)
        try:
            priority_id = await self._subscriber.spop("anomalies:priority:set")
            if priority_id:
                if isinstance(priority_id, bytes | bytearray):
                    priority_id = priority_id.decode("utf-8", errors="replace")
                # Guard against a now-stale entry: the row may have
                # been processed since the SADD (e.g. by an earlier
                # LIFO pick). Fall through to DB poll if so.
                async with self._pool.acquire() as conn:
                    is_pending = await conn.fetchval(
                        "SELECT 1 FROM anomalies "
                        "WHERE id = $1 AND explanation_status = 'pending'",
                        priority_id,
                    )
                if is_pending:
                    return priority_id
        except Exception:  # noqa: BLE001
            log.exception("priority-set check failed; falling back to DB poll")

        # 2. LIFO DB poll (newest pending first)
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT id FROM anomalies "
                "WHERE explanation_status = 'pending' "
                "ORDER BY detected_at DESC LIMIT 1"
            )
        return row["id"] if row else None

    # -- per-message work --------------------------------------------------

    async def _handle_one(self, anomaly_id: str) -> None:
        anomaly = await repository.get_anomaly(self._pool, anomaly_id)
        if anomaly is None:
            log.warning("explainer: anomaly %s not in DB; skipping", anomaly_id)
            self.stats.not_found += 1
            return

        # 1. embed the anomaly's log template for FAISS retrieval.
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

        # 4. call LLaMA — wrapped in `asyncio.wait_for` as a hard
        # belt-and-suspenders bound on top of the httpx timeout.
        # Without this guard, a half-open socket or a wedged Ollama
        # process would block the worker indefinitely (we have a single
        # worker; one stuck call freezes every queued anomaly behind
        # it). The outer ceiling is the client timeout + 30 s grace,
        # so under healthy operation httpx fires first and we get a
        # clean error path; the asyncio cap only triggers when httpx
        # itself fails to honour its own timeout.
        client_timeout = float(getattr(self._llama, "timeout_s", 900.0))
        worker_timeout = client_timeout + 30.0
        prompt_chars = len(SYSTEM_PROMPT) + len(user_prompt)
        log.info(
            "explainer: start anomaly=%s prompt_chars=%d k=%d worker_timeout_s=%.0f",
            anomaly_id, prompt_chars, len(retrieved), worker_timeout,
        )
        t0 = time.monotonic()
        try:
            raw = await asyncio.wait_for(
                self._llama.generate(
                    system=SYSTEM_PROMPT,
                    user=user_prompt,
                    request_id=anomaly_id,
                ),
                timeout=worker_timeout,
            )
        except asyncio.TimeoutError:
            elapsed = time.monotonic() - t0
            log.error(
                "explainer: WORKER TIMEOUT anomaly=%s elapsed_s=%.1f "
                "limit_s=%.0f — marking failed so the queue can drain",
                anomaly_id, elapsed, worker_timeout,
            )
            await self._mark_failed(anomaly_id)
            self.stats.failed += 1
            return

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

        elapsed = time.monotonic() - t0
        self.stats.explained += 1
        log.info(
            "explainer: ready anomaly=%s elapsed_s=%.1f response_chars=%d "
            "k=%d model=%s",
            anomaly_id, elapsed, len(raw), len(retrieved),
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


DEFAULT_CACHE_PATH = Path(__file__).resolve().parent.parent / "artifacts" / "precomputed_explanations.json"

# top_k for the LIVE LLaMA path. Reduced from the FAISS-default 3 to 1
# so the prompt is shorter and Ollama generation is ~30% faster on the
# rare cache-miss case. The precompute script uses k=3 itself for
# richer cached explanations — only the runtime worker is tightened.
LIVE_TOP_K = 1


async def build_default_explainer(
    *,
    redis_url: str | None = None,
    db_url: str | None = None,
    index_path: str | Path | None = None,
    records_path: str | Path | None = None,
    top_k: int = LIVE_TOP_K,
) -> tuple[RagExplainer, ExplainerResources]:
    """Wire up the production explainer from env vars / defaults.

    Returns the explainer + a resources bag the caller closes on
    shutdown. Failure to connect to any of (Redis, Postgres, FAISS,
    Ollama) raises here so the process exits early — better than
    silently consuming messages that we can't process.

    Every anomaly is explained via a live Ollama call — no precomputed
    cache short-circuit. Latency is bounded by the model + hardware:
      * llama3.2:1b on CPU  → ~15-30 s per call
      * llama3:8b   on CPU  → ~60-180 s per call
      * llama3:8b   on GPU  → ~3-5 s per call
    Set `LOGGUARD_LLAMA_HOST` to point at a remote GPU-hosted Ollama
    when running off a laptop CPU.
    """
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
        cache=None,  # cache disabled — every anomaly hits live LLaMA
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
