r"""
Step 4b-iii — live ingestion runner.

Glues the existing Step 4 building blocks together end-to-end:

  Redis stream `logs:raw`
    │
    ▼
  ingestion.consumer.LogStreamConsumer  (XREAD)
    │
    ▼
  ingestion.parser.LogParser            (Drain3 match-only)
    │
    ▼
  ingestion.sequence_builder.WindowBuilder (sliding-window 20 / stride 1)
    │
    ▼
  ml.embedder.embed_window              (SBERT per-event, normalised)
    │
    ▼
  ml.detector.Detector.score            (Transformer + AE + Confidence MLP)
    │ if !is_anomaly → drop
    ▼
  ml.postprocess.decide_severity        (critical | warning | info)
  ml.postprocess.Deduplicator           (60s template+source clustering)
  ml.postprocess.build_anomaly          (canonical Anomaly Pydantic)
    │
    ├─► api.repository.insert_anomaly   (Postgres)
    └─► Redis PUBLISH
          ├─ anomalies:broadcast        (consumed by api.ws \-→ frontend)
          └─ anomalies:detected         (consumed by Step 5 RAG worker)

Runs as its own process (`python -m ingestion.runner`), separate from
the FastAPI app — that lets us scale them independently and crash one
without taking the API down. Both share the same Postgres database and
same Redis instance via env vars.

The runner is intentionally testable: every external dependency is
injected through `__init__`, so unit tests stub them with fakes and
assert the wiring without touching real Redis / Postgres / Torch.
`build_default_runner()` is the production wiring helper.
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import asyncpg
import redis.asyncio as redis_aio

from api import repository
from api.db import DB_URL_ENV, create_pool
from api.repository import install_jsonb_codec
from api.schemas import Anomaly
from ingestion.consumer import (
    DEFAULT_DRAIN3_STATE,
    DEFAULT_REDIS_URL,
    DEFAULT_STREAM,
    LogStreamConsumer,
    WindowedConsumer,
)
from ingestion.parser import LogParser
from ingestion.sequence_builder import Window, WindowBuilder
from ml.detector import DetectionResult, Detector
from ml.embedder import SBertLike, embed_window, load_default_sbert
from ml.postprocess import (
    AnomalyContext,
    Deduplicator,
    build_anomaly,
    decide_severity,
)

log = logging.getLogger(__name__)

DEFAULT_ARTIFACTS_DIR = "artifacts"

# Pubsub channel names — pinned here so the WS subscriber and the RAG
# worker can't drift from what the runner actually publishes on.
CHANNEL_BROADCAST = "anomalies:broadcast"
CHANNEL_DETECTED = "anomalies:detected"


@dataclass
class RunnerStats:
    """Lightweight observability — counts roll up on every window
    processed. Exposed for tests + CLI summary on shutdown."""
    windows_seen: int = 0
    anomalies_emitted: int = 0
    anomalies_suppressed: int = 0  # below threshold or low confidence
    publish_failures: int = 0


class IngestionRunner:
    """End-to-end pipeline. All dependencies injected for testability —
    `build_default_runner()` constructs the production wiring.

    The runner doesn't own the lifecycle of the things it borrows
    (consumer, pool, redis client, detector). Whoever constructs it is
    responsible for closing them — see `_run_cli` for the canonical
    teardown sequence.
    """

    def __init__(
        self,
        *,
        consumer: WindowedConsumer,
        embedder_model: SBertLike,
        detector: Detector,
        deduplicator: Deduplicator,
        pool: asyncpg.Pool,
        publisher: redis_aio.Redis,
    ) -> None:
        self._consumer = consumer
        self._embedder = embedder_model
        self._detector = detector
        self._dedup = deduplicator
        self._pool = pool
        self._publisher = publisher
        self.stats = RunnerStats()

    async def run(self) -> None:
        """Iterate windows from the consumer until cancelled."""
        async for window in self._consumer.windows():
            try:
                await self._process_window(window)
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                # One bad window must not poison the pipeline. Log loudly,
                # bump the failure counter, keep going.
                log.exception("runner: process_window failed for window=%s", window.window_id)
                self.stats.publish_failures += 1

    async def _process_window(self, window: Window) -> None:
        self.stats.windows_seen += 1

        emb = embed_window(window, model=self._embedder)
        detection = self._detector.score(emb)
        if not self._detector.is_anomaly(detection):
            self.stats.anomalies_suppressed += 1
            return

        anomaly = self._build_anomaly_for(window, detection)
        await repository.insert_anomaly(self._pool, anomaly)
        await self._publish(anomaly)
        self.stats.anomalies_emitted += 1

    def _build_anomaly_for(self, window: Window, detection: DetectionResult) -> Anomaly:
        detected_at = datetime.now(UTC)
        severity = decide_severity(detection, window.source)
        cluster_id, cluster_size = self._dedup.assign(
            template=window.templates[-1],
            source=window.source,
            detected_at=detected_at,
        )
        ctx = AnomalyContext(
            window=window,
            detection=detection,
            severity=severity,
            cluster_id=cluster_id,
            cluster_size=cluster_size,
            detected_at=detected_at,
        )
        return build_anomaly(ctx)

    async def _publish(self, anomaly: Anomaly) -> None:
        """Publish to two channels: broadcast (for live WS clients) and
        detected (for the Step 5 RAG worker). Broadcast carries the full
        Anomaly JSON; detected carries just the id since the RAG worker
        will re-fetch the row from Postgres anyway."""
        payload = anomaly.model_dump_json()
        await self._publisher.publish(CHANNEL_BROADCAST, payload)
        await self._publisher.publish(CHANNEL_DETECTED, anomaly.id)


# -- production wiring -----------------------------------------------------


async def build_default_runner(
    *,
    redis_url: str | None = None,
    stream: str | None = None,
    drain3_state: str | Path | None = None,
    artifacts_dir: str | Path | None = None,
    db_url: str | None = None,
) -> tuple[IngestionRunner, list]:
    """Wire up the production pipeline from env vars / defaults.

    Returns the runner alongside a list of resources the caller must
    close on shutdown (so cancellation / SIGTERM tear down cleanly).
    """
    redis_url = redis_url or os.environ.get("LOGGUARD_REDIS_URL", DEFAULT_REDIS_URL)
    stream = stream or os.environ.get("LOGGUARD_INGEST_STREAM", DEFAULT_STREAM)
    drain3_state = drain3_state or os.environ.get(
        "LOGGUARD_DRAIN3_STATE", DEFAULT_DRAIN3_STATE
    )
    artifacts_dir = artifacts_dir or os.environ.get(
        "LOGGUARD_ARTIFACTS_DIR", DEFAULT_ARTIFACTS_DIR
    )
    db_url = db_url or os.environ.get(DB_URL_ENV)
    if not db_url:
        raise RuntimeError(
            f"{DB_URL_ENV} not set — runner needs Postgres to persist anomalies."
        )

    consumer_redis = redis_aio.from_url(redis_url, decode_responses=True)
    publisher_redis = redis_aio.from_url(redis_url, decode_responses=True)

    pool = await create_pool(db_url)
    async with pool.acquire() as conn:
        await install_jsonb_codec(conn)

    parser = LogParser(drain3_state)
    stream_consumer = LogStreamConsumer(consumer_redis, parser, stream=stream)
    windowed = WindowedConsumer(stream_consumer, window_builder=WindowBuilder())

    detector = Detector.from_artifacts(artifacts_dir)
    embedder = load_default_sbert()
    dedup = Deduplicator()

    runner = IngestionRunner(
        consumer=windowed,
        embedder_model=embedder,
        detector=detector,
        deduplicator=dedup,
        pool=pool,
        publisher=publisher_redis,
    )
    # Order matters on shutdown: pool first (commits in flight), then
    # publishers, then the consumer client.
    closables = [pool, publisher_redis, consumer_redis]
    return runner, closables


async def _close_all(resources: list) -> None:
    for r in resources:
        try:
            if isinstance(r, asyncpg.Pool):
                await r.close()
            else:
                await r.aclose()
        except Exception:  # noqa: BLE001
            log.exception("runner: failed to close %r", r)


async def _run_cli() -> int:  # pragma: no cover — interactive runner
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    log.info("ingestion runner: starting")
    runner, closables = await build_default_runner()
    log.info(
        "ingestion runner: ready (drain3=%d templates, threshold=%.2f, conf_threshold=%.2f)",
        runner._consumer._consumer._parser.template_count,
        runner._detector.thresholds.anomaly_threshold,
        runner._detector.thresholds.confidence_threshold,
    )
    try:
        await runner.run()
    except asyncio.CancelledError:
        log.info("ingestion runner: cancelled, shutting down")
    finally:
        await _close_all(closables)
        log.info(
            "ingestion runner: stopped. windows=%d emitted=%d suppressed=%d failures=%d",
            runner.stats.windows_seen,
            runner.stats.anomalies_emitted,
            runner.stats.anomalies_suppressed,
            runner.stats.publish_failures,
        )
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(asyncio.run(_run_cli()))
