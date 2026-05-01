"""
Tests for `ingestion.runner.IngestionRunner`.

Strategy: stub every external dependency so we can pin the wiring
without spinning up Redis / Postgres / Torch. The dependencies that
matter:

  * Consumer — feeds Windows.
  * Detector — turns embeddings into DetectionResults + the anomaly gate.
  * Pool — DB writes go through `repository.insert_anomaly`.
  * Publisher — Redis pubsub `publish` calls.

We patch `repository.insert_anomaly` and feed a fake publisher with a
list-recording `publish` method. The detector and embedder are stub
classes that return canned values.
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import patch

import pytest

from api.schemas import Anomaly
from ingestion.runner import (
    CHANNEL_BROADCAST,
    CHANNEL_DETECTED,
    IngestionRunner,
)
from ingestion.sequence_builder import ParsedLog, Window, build_windows
from ml.detector import DetectionResult
from ml.postprocess import Deduplicator
from ml.transformer import WINDOW_LEN

# -- stubs ------------------------------------------------------------------


class _StubConsumer:
    """Acts like WindowedConsumer for the runner — yields a fixed list
    of windows, then stops (drives `async for window in consumer.windows()`
    to exit cleanly so the test doesn't hang)."""

    def __init__(self, windows: list[Window]) -> None:
        self._windows = windows

    async def windows(self) -> AsyncIterator[Window]:
        for w in self._windows:
            yield w


class _StubEmbedder:
    """SBERT stand-in: returns a deterministic vector. Embedder code
    expects a `.encode(sentences, ...)` method per the SBertLike
    Protocol; the runner's call path goes through embed_window which
    calls embed_windows which calls model.encode."""

    dim = 8

    def encode(self, sentences, batch_size=64, normalize_embeddings=True, show_progress_bar=False):
        import numpy as np
        return np.zeros((len(sentences), self.dim), dtype=np.float32)


class _StubDetector:
    """Returns a canned DetectionResult and a configurable is_anomaly()
    predicate so tests can drive the gate."""

    def __init__(self, *, anomaly: bool, transformer_prob: float = 0.5,
                 ensemble: float = 0.6, confidence: float = 0.7) -> None:
        self._anomaly = anomaly
        self._transformer_prob = transformer_prob
        self._ensemble = ensemble
        self._confidence = confidence

    def score(self, embedding) -> DetectionResult:
        return DetectionResult(
            ensemble_score=self._ensemble,
            transformer_prob=self._transformer_prob,
            ae_error_raw=0.0,
            ae_error_normalised=0.0,
            confidence=self._confidence,
            predicted_failure_minutes=5,
            attention=tuple([1.0 / WINDOW_LEN] * WINDOW_LEN),
        )

    def is_anomaly(self, detection: DetectionResult) -> bool:
        return self._anomaly


class _RecordingPublisher:
    """Captures every (channel, payload) tuple passed to publish()."""

    def __init__(self) -> None:
        self.published: list[tuple[str, str]] = []

    async def publish(self, channel: str, payload: Any) -> int:
        self.published.append((channel, payload))
        return 1


# -- helpers ----------------------------------------------------------------


def _events(n: int, source: str = "host-1") -> list[ParsedLog]:
    return [
        ParsedLog(
            raw=f"line {i}",
            template=f"INFO template_{i % 3}",
            template_id=str(i % 3),
            source=source,
            line_no=i,
        )
        for i in range(n)
    ]


def _window(source: str = "host-1") -> Window:
    return build_windows(_events(WINDOW_LEN, source=source))[0]


# -- tests ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_runner_emits_an_anomaly_when_detector_fires():
    publisher = _RecordingPublisher()
    captured_inserts: list[Anomaly] = []

    async def fake_insert(_pool, anomaly):
        captured_inserts.append(anomaly)

    runner = IngestionRunner(
        consumer=_StubConsumer([_window()]),
        embedder_model=_StubEmbedder(),
        detector=_StubDetector(anomaly=True, ensemble=0.9),
        deduplicator=Deduplicator(),
        pool=None,  # Not used directly — repository.insert_anomaly is patched.
        publisher=publisher,
    )

    with patch("ingestion.runner.repository.insert_anomaly", side_effect=fake_insert):
        await runner.run()

    # Wiring assertions
    assert len(captured_inserts) == 1
    assert isinstance(captured_inserts[0], Anomaly)

    channels = {c for c, _ in publisher.published}
    assert channels == {CHANNEL_BROADCAST, CHANNEL_DETECTED}

    # Stats
    assert runner.stats.windows_seen == 1
    assert runner.stats.anomalies_emitted == 1
    assert runner.stats.anomalies_suppressed == 0
    assert runner.stats.publish_failures == 0


@pytest.mark.asyncio
async def test_runner_suppresses_when_detector_says_not_anomaly():
    """Below-threshold windows must not insert and must not publish."""
    publisher = _RecordingPublisher()

    async def fake_insert(*_args, **_kwargs):
        raise AssertionError("insert called for a non-anomaly window")

    runner = IngestionRunner(
        consumer=_StubConsumer([_window()]),
        embedder_model=_StubEmbedder(),
        detector=_StubDetector(anomaly=False),
        deduplicator=Deduplicator(),
        pool=None,
        publisher=publisher,
    )

    with patch("ingestion.runner.repository.insert_anomaly", side_effect=fake_insert):
        await runner.run()

    assert publisher.published == []
    assert runner.stats.windows_seen == 1
    assert runner.stats.anomalies_emitted == 0
    assert runner.stats.anomalies_suppressed == 1


@pytest.mark.asyncio
async def test_runner_publishes_full_anomaly_json_on_broadcast_channel():
    """The broadcast payload must be the canonical Anomaly JSON — the
    WS handler forwards it verbatim, so any drift here breaks the
    frontend silently. The detected channel carries just the id."""
    publisher = _RecordingPublisher()

    async def fake_insert(*_args, **_kwargs):
        return None

    runner = IngestionRunner(
        consumer=_StubConsumer([_window(source="nova-1")]),
        embedder_model=_StubEmbedder(),
        detector=_StubDetector(anomaly=True, ensemble=0.92),
        deduplicator=Deduplicator(),
        pool=None,
        publisher=publisher,
    )

    with patch("ingestion.runner.repository.insert_anomaly", side_effect=fake_insert):
        await runner.run()

    by_channel = dict(publisher.published)
    # Broadcast: full JSON (parses as Anomaly)
    broadcast_payload = by_channel[CHANNEL_BROADCAST]
    parsed = Anomaly.model_validate_json(broadcast_payload)
    assert parsed.source == "nova-1"
    assert parsed.severity in ("critical", "warning", "info")

    # Detected: just the id
    detected_payload = by_channel[CHANNEL_DETECTED]
    assert detected_payload == parsed.id


@pytest.mark.asyncio
async def test_runner_continues_on_one_failed_window():
    """A failed window must not poison the pipeline. Two windows in,
    one fails the insert, the second still emits."""
    publisher = _RecordingPublisher()
    insert_calls = []

    async def flaky_insert(_pool, anomaly):
        insert_calls.append(anomaly)
        if len(insert_calls) == 1:
            raise RuntimeError("simulated DB hiccup")

    runner = IngestionRunner(
        consumer=_StubConsumer([_window(source="a"), _window(source="b")]),
        embedder_model=_StubEmbedder(),
        detector=_StubDetector(anomaly=True),
        deduplicator=Deduplicator(),
        pool=None,
        publisher=publisher,
    )

    with patch("ingestion.runner.repository.insert_anomaly", side_effect=flaky_insert):
        await runner.run()

    # Two windows seen, one emitted, one failure logged.
    assert runner.stats.windows_seen == 2
    assert runner.stats.anomalies_emitted == 1
    assert runner.stats.publish_failures == 1
    # Only the second window's anomaly was published (first one failed before publish).
    assert len([c for c, _ in publisher.published if c == CHANNEL_BROADCAST]) == 1


@pytest.mark.asyncio
async def test_runner_dedup_clusters_consecutive_same_template_same_source():
    """Two windows with the same template + source within the dedup
    window should land on the same cluster_id with cluster_size 2."""
    publisher = _RecordingPublisher()
    captured: list[Anomaly] = []

    async def fake_insert(_pool, anomaly):
        captured.append(anomaly)

    # Both windows identical → same template + same source.
    w = _window(source="nova-1")
    runner = IngestionRunner(
        consumer=_StubConsumer([w, w]),
        embedder_model=_StubEmbedder(),
        detector=_StubDetector(anomaly=True),
        deduplicator=Deduplicator(),
        pool=None,
        publisher=publisher,
    )

    with patch("ingestion.runner.repository.insert_anomaly", side_effect=fake_insert):
        await runner.run()

    assert len(captured) == 2
    assert captured[0].cluster_id == captured[1].cluster_id
    assert captured[0].cluster_size == 1
    assert captured[1].cluster_size == 2
