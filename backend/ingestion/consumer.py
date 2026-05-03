"""
Step 4 — live log ingestion.

Reads raw log lines from the `logs:raw` Redis stream, parses each through
Drain3 (matching against the persisted training state), feeds the parsed
events into the streaming `WindowBuilder`, and yields completed windows.

The detector + WS broadcast are layered on top in Step 4b — this module
is intentionally agnostic of what happens to the windows downstream so it
stays trivially testable.

Stream contract (entries pushed by `tools/log_replay.py`):

    XADD logs:raw * line "INFO nova-api ..." source "nova-api-prod-3"

Both fields are required. `source` is preserved on every ParsedLog and
flows through to the Window so downstream code knows which host emitted it.

CLI entrypoint (visual smoke test once a state file exists):

    python -m ingestion.consumer

prints one line per parsed event and a window summary every WINDOW_SIZE
events. Connects to `LOGGUARD_REDIS_URL` (default `redis://localhost:6379`)
and the stream `LOGGUARD_INGEST_STREAM` (default `logs:raw`).
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import redis.asyncio as redis_aio

from ingestion.parser import LogParser
from ingestion.sequence_builder import ParsedLog, Window, WindowBuilder

log = logging.getLogger(__name__)

# Field names inside each XADD entry. Pinned here so log_replay.py and the
# consumer can't drift apart silently.
FIELD_LINE = "line"
FIELD_SOURCE = "source"
# Optional. Producers that don't include `origin` (live demo replay,
# legacy clients) implicitly mean "live-stream".
FIELD_ORIGIN = "origin"
DEFAULT_ORIGIN = "live-stream"

DEFAULT_REDIS_URL = "redis://localhost:6379"
DEFAULT_STREAM = "logs:raw"
DEFAULT_DRAIN3_STATE = "artifacts/drain3_state.bin"

# Block this long on XREAD before returning (so the loop can be cleanly
# cancelled by an asyncio shutdown signal).
XREAD_BLOCK_MS = 1_000
# How many entries to ask for per XREAD round-trip. Small enough to feel
# real-time, large enough that we're not chatty under load.
XREAD_COUNT = 64


class LogStreamConsumer:
    """Async Redis-stream → ParsedLog pump.

    Iterate with `async for event in consumer.events():` to receive parsed
    events one at a time. Each call to `events()` resumes from the last id
    seen by this consumer instance, so it's safe to break out of the loop
    and re-enter.

    Decoupled from windowing on purpose — `WindowedConsumer` composes this
    with `WindowBuilder` for the more common "give me windows" use case,
    but raw events are useful for tests and debugging.
    """

    def __init__(
        self,
        redis_client: redis_aio.Redis,
        parser: LogParser,
        *,
        stream: str = DEFAULT_STREAM,
        start_id: str = "0-0",
        block_ms: int = XREAD_BLOCK_MS,
        count: int = XREAD_COUNT,
    ) -> None:
        self._redis = redis_client
        self._parser = parser
        self._stream = stream
        self._last_id = start_id
        self._block_ms = block_ms
        self._count = count

    async def events(self) -> AsyncIterator[ParsedLog]:
        """Yield ParsedLog instances forever (until the task is cancelled)."""
        while True:
            try:
                response = await self._redis.xread(
                    {self._stream: self._last_id},
                    count=self._count,
                    block=self._block_ms,
                )
            except asyncio.CancelledError:
                raise
            except Exception:  # pragma: no cover — covered by integration tests
                # Don't crash the consumer on a transient Redis hiccup; back
                # off briefly and retry. The XREAD will reconnect via the
                # client's pool.
                log.exception("xread failed, retrying after backoff")
                await asyncio.sleep(0.5)
                continue

            if not response:
                # Block timeout fired with no entries — go round again.
                continue

            # `response` is [(stream_name, [(id, {field: value}), ...])]
            for _stream, entries in response:
                for entry_id, fields in entries:
                    self._last_id = _to_str(entry_id)
                    line = fields.get(FIELD_LINE) or fields.get(FIELD_LINE.encode())
                    source = fields.get(FIELD_SOURCE) or fields.get(FIELD_SOURCE.encode())
                    origin = (
                        fields.get(FIELD_ORIGIN)
                        or fields.get(FIELD_ORIGIN.encode())
                        or DEFAULT_ORIGIN
                    )
                    if line is None or source is None:
                        log.warning(
                            "stream entry missing 'line' or 'source' field; skipping (id=%s)",
                            self._last_id,
                        )
                        continue
                    yield self._parser.parse(
                        _to_str(line), _to_str(source), origin=_to_str(origin),
                    )


class WindowedConsumer:
    """Compose `LogStreamConsumer` with `WindowBuilder` to yield Windows.

    This is what Step 4b's detection loop will iterate over. One Window
    surfaces per stride-step once the sliding buffer is full.
    """

    def __init__(
        self,
        consumer: LogStreamConsumer,
        *,
        window_builder: WindowBuilder | None = None,
    ) -> None:
        self._consumer = consumer
        self._builder = window_builder or WindowBuilder()

    async def windows(self) -> AsyncIterator[Window]:
        async for event in self._consumer.events():
            window = self._builder.step(event)
            if window is not None:
                yield window


# -- helpers --------------------------------------------------------------


def _to_str(value: Any) -> str:
    """Normalise bytes/str to str. redis-py decodes when `decode_responses=True`,
    but tolerating both keeps the consumer robust to clients configured either way."""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


# -- factory + CLI runner -------------------------------------------------


async def build_default_consumer(
    *,
    redis_url: str | None = None,
    stream: str | None = None,
    drain3_state: str | Path | None = None,
) -> tuple[redis_aio.Redis, WindowedConsumer]:
    """Build a WindowedConsumer wired to a real Redis client.

    Reads each parameter from its `LOGGUARD_*` env var if not passed
    explicitly. Returns the redis client alongside the consumer so the
    caller can `await client.aclose()` on shutdown.
    """
    redis_url = redis_url or os.environ.get("LOGGUARD_REDIS_URL", DEFAULT_REDIS_URL)
    stream = stream or os.environ.get("LOGGUARD_INGEST_STREAM", DEFAULT_STREAM)
    drain3_state = drain3_state or os.environ.get(
        "LOGGUARD_DRAIN3_STATE", DEFAULT_DRAIN3_STATE
    )

    client = redis_aio.from_url(redis_url, decode_responses=True)
    parser = LogParser(drain3_state)
    consumer = LogStreamConsumer(client, parser, stream=stream)
    return client, WindowedConsumer(consumer)


async def _run_cli() -> int:  # pragma: no cover — interactive runner
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    log.info("starting ingestion consumer")
    client, consumer = await build_default_consumer()
    log.info(
        "loaded drain3 state with %d templates", consumer._consumer._parser.template_count
    )
    n_events = 0
    n_windows = 0
    try:
        async for window in consumer.windows():
            n_windows += 1
            n_events = window.line_range[1] + 1  # inclusive end
            log.info(
                "window#%d  source=%s  lines=%d..%d  templates=%s",
                n_windows,
                window.source,
                window.line_range[0],
                window.line_range[1],
                window.templates[:3] + ["..."] if len(window.templates) > 3 else window.templates,
            )
    except asyncio.CancelledError:
        pass
    finally:
        await client.aclose()
        log.info("shut down. saw %d events / %d windows.", n_events, n_windows)
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(asyncio.run(_run_cli()))
