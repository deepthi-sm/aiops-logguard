"""
Tests for `tools.log_replay`.

Two layers:
  * Pure-function tests for the source-pool picker (no Redis needed).
  * One end-to-end smoke that pushes lines through fakeredis and reads
    the resulting stream entries back, asserting the schema + batching
    contract the consumer depends on.

The most important test is `test_critical_sources_match_postprocess`:
the replay tool's CRITICAL_SOURCES MUST stay byte-identical to
`ml.postprocess.DEFAULT_CRITICAL_SOURCES`. If they drift, the demo's
critical-severity tier silently never fires.
"""
from __future__ import annotations

import asyncio
import random
from pathlib import Path

import fakeredis.aioredis
import pytest

from ingestion.consumer import DEFAULT_STREAM, FIELD_LINE, FIELD_SOURCE
from ingestion.sequence_builder import WINDOW_SIZE
from ml.postprocess import DEFAULT_CRITICAL_SOURCES
from tools.log_replay import (
    CRITICAL_SOURCES,
    NON_CRITICAL_SOURCES,
    make_batch_source_picker,
    replay,
)

# -- contract: source pool matches postprocess ----------------------------


def test_critical_sources_match_postprocess():
    """Every name in the replay tool's CRITICAL_SOURCES tuple must also
    be in `ml.postprocess.DEFAULT_CRITICAL_SOURCES`. Reverse is no
    longer required: postprocess now also includes "user-upload" and
    "mixed" so demo uploads can produce critical anomalies — those are
    not log_replay sources, so the relation became subset, not equal."""
    assert set(CRITICAL_SOURCES) <= set(DEFAULT_CRITICAL_SOURCES)


def test_critical_and_non_critical_pools_are_disjoint():
    """Sanity: a hostname tagged 'non-critical' here must never also
    appear in CRITICAL_SOURCES — otherwise the critical-fraction split
    is meaningless."""
    overlap = set(CRITICAL_SOURCES) & set(NON_CRITICAL_SOURCES)
    assert overlap == set(), f"overlap: {overlap}"


# -- source picker --------------------------------------------------------


class TestSourcePicker:
    def test_picker_yields_only_known_sources(self):
        rng = random.Random(0)
        pick = make_batch_source_picker(critical_fraction=0.5, rng=rng)
        known = set(CRITICAL_SOURCES) | set(NON_CRITICAL_SOURCES)
        for _ in range(200):
            assert pick() in known

    def test_critical_fraction_zero_never_picks_critical(self):
        rng = random.Random(0)
        pick = make_batch_source_picker(critical_fraction=0.0, rng=rng)
        critical = set(CRITICAL_SOURCES)
        for _ in range(200):
            assert pick() not in critical

    def test_critical_fraction_one_always_picks_critical(self):
        rng = random.Random(0)
        pick = make_batch_source_picker(critical_fraction=1.0, rng=rng)
        critical = set(CRITICAL_SOURCES)
        for _ in range(200):
            assert pick() in critical

    def test_critical_fraction_half_lands_roughly_half(self):
        """With 1000 picks at 0.5, expect 500 ± a wide tolerance for
        binomial variance. This is a smoke test, not a tight bound."""
        rng = random.Random(0)
        pick = make_batch_source_picker(critical_fraction=0.5, rng=rng)
        critical = set(CRITICAL_SOURCES)
        n = 1000
        hits = sum(1 for _ in range(n) if pick() in critical)
        # 95 % CI for Binomial(1000, 0.5) ≈ 469..531; allow 400..600 for safety
        assert 400 <= hits <= 600, f"got {hits}/{n} critical picks"

    def test_invalid_fraction_raises(self):
        with pytest.raises(ValueError):
            make_batch_source_picker(critical_fraction=-0.1)
        with pytest.raises(ValueError):
            make_batch_source_picker(critical_fraction=1.5)


# -- replay end-to-end via fakeredis --------------------------------------


@pytest.fixture
async def fake_redis():
    client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    yield client
    await client.aclose()


async def test_replay_emits_correct_xadd_schema(fake_redis, tmp_path: Path):
    """Each XADD must carry exactly the fields the consumer reads —
    `line` and `source`. Batch size 5 here so the test runs quickly."""
    log_file = tmp_path / "input.log"
    log_file.write_text(
        "\n".join(f"INFO line {i}" for i in range(15)) + "\n",
        encoding="utf-8",
    )

    stats = await replay(
        fake_redis,
        input_path=log_file,
        stream=DEFAULT_STREAM,
        rate=1000,  # very fast — 1ms per line
        loop=False,
        max_lines=None,
        critical_fraction=1.0,  # all critical so we can assert
        batch_size=5,
        rng=random.Random(42),
    )

    assert stats.lines_emitted == 15
    assert stats.batches_emitted == 3
    assert stats.critical_batches == 3

    entries = await fake_redis.xrange(DEFAULT_STREAM)
    assert len(entries) == 15
    for _entry_id, fields in entries:
        assert FIELD_LINE in fields
        assert FIELD_SOURCE in fields
        assert fields[FIELD_SOURCE] in CRITICAL_SOURCES


async def test_replay_batches_keep_source_consistent(fake_redis, tmp_path: Path):
    """Within a batch of `batch_size` lines, source must NOT change —
    otherwise WindowBuilder will produce 'mixed' source windows and
    the critical tier will never fire."""
    log_file = tmp_path / "input.log"
    log_file.write_text(
        "\n".join(f"line {i}" for i in range(20)) + "\n",
        encoding="utf-8",
    )

    await replay(
        fake_redis,
        input_path=log_file,
        stream=DEFAULT_STREAM,
        rate=1000,
        loop=False,
        max_lines=None,
        critical_fraction=0.5,
        batch_size=5,
        rng=random.Random(0),
    )

    entries = await fake_redis.xrange(DEFAULT_STREAM)
    sources = [fields[FIELD_SOURCE] for _id, fields in entries]
    # Group every 5 consecutive sources — each group must be uniform.
    assert len(sources) == 20
    for start in range(0, 20, 5):
        chunk = sources[start : start + 5]
        assert len(set(chunk)) == 1, f"batch at index {start} has mixed source: {chunk}"


async def test_replay_default_batch_size_is_window_size(fake_redis, tmp_path: Path):
    """Default batch_size matches WINDOW_SIZE so each batch produces at
    least one source-coherent window. Pin this so a future refactor
    can't silently break the demo's critical-tier logic."""
    log_file = tmp_path / "input.log"
    log_file.write_text(
        "\n".join(f"line {i}" for i in range(WINDOW_SIZE * 2)) + "\n",
        encoding="utf-8",
    )

    stats = await replay(
        fake_redis,
        input_path=log_file,
        stream=DEFAULT_STREAM,
        rate=1000,
        loop=False,
        max_lines=None,
        critical_fraction=0.5,
        # batch_size omitted on purpose — picks up the default
        rng=random.Random(0),
    )

    # WINDOW_SIZE * 2 lines / WINDOW_SIZE per batch = 2 batches.
    assert stats.batches_emitted == 2


async def test_replay_max_lines_caps_emission(fake_redis, tmp_path: Path):
    log_file = tmp_path / "input.log"
    log_file.write_text("\n".join(f"line {i}" for i in range(100)) + "\n", encoding="utf-8")

    stats = await replay(
        fake_redis,
        input_path=log_file,
        stream=DEFAULT_STREAM,
        rate=1000,
        loop=False,
        max_lines=12,
        critical_fraction=0.5,
        batch_size=5,
        rng=random.Random(0),
    )
    assert stats.lines_emitted == 12


async def test_replay_skips_blank_lines(fake_redis, tmp_path: Path):
    log_file = tmp_path / "input.log"
    log_file.write_text(
        "INFO real line 1\n\n   \nINFO real line 2\n\nINFO real line 3\n",
        encoding="utf-8",
    )
    stats = await replay(
        fake_redis,
        input_path=log_file,
        stream=DEFAULT_STREAM,
        rate=1000,
        loop=False,
        max_lines=None,
        critical_fraction=0.5,
        batch_size=5,
        rng=random.Random(0),
    )
    assert stats.lines_emitted == 3


async def test_replay_loop_restarts_at_eof(fake_redis, tmp_path: Path):
    """When --loop is set, the file restarts from the top until max_lines
    fires (or the task is cancelled)."""
    log_file = tmp_path / "tiny.log"
    log_file.write_text("INFO a\nINFO b\n", encoding="utf-8")

    stats = await replay(
        fake_redis,
        input_path=log_file,
        stream=DEFAULT_STREAM,
        rate=1000,
        loop=True,
        max_lines=10,
        critical_fraction=0.5,
        batch_size=2,
        rng=random.Random(0),
    )
    assert stats.lines_emitted == 10  # 5 passes through the 2-line file


async def test_replay_invalid_rate_raises(fake_redis, tmp_path: Path):
    log_file = tmp_path / "x.log"
    log_file.write_text("line 1\n", encoding="utf-8")
    with pytest.raises(ValueError):
        await replay(
            fake_redis,
            input_path=log_file,
            stream=DEFAULT_STREAM,
            rate=0,
            loop=False,
            max_lines=1,
            critical_fraction=0.5,
            batch_size=5,
        )


async def test_replay_missing_input_file_raises(fake_redis, tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        await replay(
            fake_redis,
            input_path=tmp_path / "does_not_exist.log",
            stream=DEFAULT_STREAM,
            rate=10,
            loop=False,
            max_lines=None,
            critical_fraction=0.5,
            batch_size=5,
        )


# Suppress unused-import warning from asyncio
_ = asyncio
