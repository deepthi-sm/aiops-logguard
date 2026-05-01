"""
Tests for the live-ingestion Redis consumer.

Uses `fakeredis` to exercise the real `redis.asyncio` API surface against
an in-memory backend, so the test pins the actual `XREAD` semantics this
PR depends on (block timeout, count limit, last-id resumption).
"""
import asyncio
from pathlib import Path

import fakeredis.aioredis
import pytest

from ingestion.consumer import (
    DEFAULT_STREAM,
    FIELD_LINE,
    FIELD_SOURCE,
    LogStreamConsumer,
    WindowedConsumer,
)
from ingestion.parser import LogParser
from ingestion.sequence_builder import WINDOW_SIZE
from training.data_prep import parse_log_file

# Each cluster needs ≥4 examples AND each line needs a distinct timestamp
# (and other variable tokens) for Drain3 to generalise them into `<*>`.
# Without varied timestamps Drain3 keeps the literal in the cluster
# template, and live lines with different timestamps fall to the unknown
# path. Real OpenStack training never hits this — synthetic fixtures do.
SYNTHETIC_TRAIN_CORPUS = """\
2026-05-01 09:00:00 INFO nova-api req-aaaa GET /v2/servers status=200 duration=42ms client=10.0.1.1
2026-05-01 09:00:01 INFO nova-api req-bbbb GET /v2/servers status=200 duration=51ms client=10.0.1.2
2026-05-01 09:00:02 INFO nova-api req-cccc GET /v2/servers status=200 duration=33ms client=10.0.1.3
2026-05-01 09:00:03 INFO nova-api req-dddd GET /v2/servers status=200 duration=27ms client=10.0.1.4
2026-05-01 09:00:04 INFO nova-api req-eeee GET /v2/servers status=200 duration=64ms client=10.0.1.5
2026-05-01 09:01:00 ERROR keystone-api req-ffff Failed to authenticate user 'alice' from 192.168.1.42
2026-05-01 09:01:01 ERROR keystone-api req-gggg Failed to authenticate user 'bob' from 192.168.1.43
2026-05-01 09:01:02 ERROR keystone-api req-hhhh Failed to authenticate user 'carol' from 192.168.1.44
2026-05-01 09:01:03 ERROR keystone-api req-iiii Failed to authenticate user 'dan' from 192.168.1.45
"""

# Live lines pushed during tests — structurally identical to the training
# corpus so Drain3.match() finds the same cluster.
LIVE_LINE_TEMPLATE = (
    "2026-05-01 09:{minute:02d}:00 INFO nova-api req-{rid} "
    "GET /v2/servers status=200 duration={dur}ms client=10.0.{a}.{b}"
)


def make_live_line(minute: int, rid: str, dur: int, a: int, b: int) -> str:
    return LIVE_LINE_TEMPLATE.format(minute=minute, rid=rid, dur=dur, a=a, b=b)


@pytest.fixture
def parser(tmp_path: Path) -> LogParser:
    """A LogParser backed by a freshly-trained drain3 state file."""
    log_path = tmp_path / "train.log"
    log_path.write_text(SYNTHETIC_TRAIN_CORPUS, encoding="utf-8")
    state_path = tmp_path / "drain3_state.bin"
    parse_log_file([log_path], drain3_state_out=state_path, source_label="test")
    return LogParser(state_path)


@pytest.fixture
async def fake_redis():
    """In-memory async Redis with `decode_responses=True` to match the
    consumer's production config."""
    client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    yield client
    await client.aclose()


async def _push(client, line: str, source: str) -> None:
    await client.xadd(DEFAULT_STREAM, {FIELD_LINE: line, FIELD_SOURCE: source})


async def _drain(consumer: LogStreamConsumer, n: int, timeout: float = 2.0) -> list:
    """Read `n` events from the consumer or raise TimeoutError."""
    events = []

    async def runner():
        async for ev in consumer.events():
            events.append(ev)
            if len(events) >= n:
                return

    await asyncio.wait_for(runner(), timeout=timeout)
    return events


async def test_consumer_yields_parsed_events(fake_redis, parser: LogParser):
    consumer = LogStreamConsumer(fake_redis, parser, block_ms=100, count=8)

    await _push(fake_redis, make_live_line(1, "xxxx", 10, 1, 99), "nova-1")
    await _push(fake_redis, make_live_line(1, "yyyy", 11, 1, 98), "nova-2")

    events = await _drain(consumer, n=2)
    assert len(events) == 2
    assert events[0].source == "nova-1"
    assert events[1].source == "nova-2"
    # Both lines share a template — line numbers monotonic.
    assert events[0].template == events[1].template
    assert events[0].template_id != "unknown"
    assert events[0].line_no == 0
    assert events[1].line_no == 1


async def test_consumer_resumes_from_last_id(fake_redis, parser: LogParser):
    """A second consumer instance with the same start_id shouldn't re-deliver
    entries that the first one already saw."""
    consumer1 = LogStreamConsumer(fake_redis, parser, block_ms=100)
    await _push(fake_redis, make_live_line(1, "aaaa", 10, 1, 50), "src-1")
    events1 = await _drain(consumer1, n=1)
    assert len(events1) == 1

    # New consumer starts where consumer1 left off.
    consumer2 = LogStreamConsumer(
        fake_redis,
        parser,
        block_ms=100,
        start_id=consumer1._last_id,
    )
    # Fresh push — consumer2 should see this one only, not the earlier entry.
    await _push(fake_redis, make_live_line(1, "bbbb", 12, 1, 51), "src-2")
    events2 = await _drain(consumer2, n=1)
    assert len(events2) == 1
    assert events2[0].source == "src-2"


async def test_consumer_skips_malformed_entries(fake_redis, parser: LogParser):
    """An entry missing 'line' or 'source' should be skipped, not crash."""
    # Bad entry first, then a good one.
    await fake_redis.xadd(DEFAULT_STREAM, {"oops": "no required fields"})
    await _push(fake_redis, make_live_line(1, "good", 10, 1, 1), "ok")

    consumer = LogStreamConsumer(fake_redis, parser, block_ms=100)
    events = await _drain(consumer, n=1)
    assert len(events) == 1
    assert events[0].source == "ok"


async def test_windowed_consumer_yields_window_after_buffer_fills(
    fake_redis, parser: LogParser
):
    """Push WINDOW_SIZE entries → exactly one Window pops out."""
    consumer = LogStreamConsumer(fake_redis, parser, block_ms=100)
    windowed = WindowedConsumer(consumer)

    for i in range(WINDOW_SIZE):
        await _push(
            fake_redis,
            make_live_line(1, f"r{i:03d}", 10 + i, 1, i + 1),
            "host-1",
        )

    windows = []

    async def runner():
        async for w in windowed.windows():
            windows.append(w)
            if len(windows) >= 1:
                return

    await asyncio.wait_for(runner(), timeout=3.0)
    assert len(windows) == 1
    assert len(windows[0].templates) == WINDOW_SIZE
    assert windows[0].source == "host-1"
