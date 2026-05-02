r"""
Step 8 — log replay tool for the live demo.

Reads a real log file (default: OpenStack abnormal+normal mix) and
streams its lines into the Redis stream `logs:raw` using the same
schema the ingestion consumer expects:

    XADD logs:raw * line "INFO nova-api ..." source "nova-api-prod-3"

Without this tool, the live runner has nothing to consume during the
demo — it sits in `XREAD ... block 1000` waiting for entries that never
arrive.

Source assignment

The runner tags an Anomaly's severity as critical only when the
window's `source` matches one of `ml.postprocess.DEFAULT_CRITICAL_SOURCES`.
A window's source is "mixed" if events disagree, otherwise it's the
shared source. So to make the critical tier actually fire during the
demo:

  * Lines are emitted in CONSECUTIVE BATCHES of WINDOW_SIZE (20) per
    source — each batch produces at least one window with a coherent
    source instead of "mixed".
  * The source pool is a mix of CRITICAL_SOURCES (must match the
    backend's `DEFAULT_CRITICAL_SOURCES` exactly) and NON_CRITICAL_SOURCES
    so the stream looks like a real multi-host environment, not all
    pages.
  * `--critical-fraction` (default 0.35) controls the per-batch coin
    flip — ~35 % of batches are tagged with a critical hostname, so
    the dashboard sees both severity tiers.

CLI

    # default — replays openstack_abnormal.log at 10 lines/sec
    python -m tools.log_replay

    # custom file + faster rate + loop forever
    python -m tools.log_replay --input training/data/openstack/openstack_normal1.log \
                               --rate 25 --loop

    # one-shot test — emit 100 lines and exit
    python -m tools.log_replay --max-lines 100 --rate 50

Env vars (all optional, fall back to defaults below):
    LOGGUARD_REDIS_URL       — default redis://localhost:6379
    LOGGUARD_INGEST_STREAM   — default logs:raw
    LOGGUARD_REPLAY_INPUT    — default training/data/openstack/openstack_abnormal.log
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import random
import sys
from collections.abc import AsyncIterator, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import redis.asyncio as redis_aio

from ingestion.consumer import DEFAULT_REDIS_URL, DEFAULT_STREAM, FIELD_LINE, FIELD_SOURCE
from ingestion.sequence_builder import WINDOW_SIZE

log = logging.getLogger(__name__)

# CONTRACT: must match `ml.postprocess.DEFAULT_CRITICAL_SOURCES` exactly.
# If those names drift apart, the critical-severity branch never matches
# and the demo silently falls back to warning/info only.
CRITICAL_SOURCES: tuple[str, ...] = (
    "nova-api-prod-3",
    "neutron-server-1",
    "glance-api-2",
    "keystone-api-2",
    "namenode-prod-1",
)

# Other plausible OpenStack/HDFS-flavoured hostnames so the demo looks
# like a real multi-host environment. None of these should appear in the
# critical set above.
NON_CRITICAL_SOURCES: tuple[str, ...] = (
    "nova-api-prod-2",
    "nova-api-prod-7",
    "neutron-server-3",
    "glance-api-3",
    "keystone-api-3",
    "datanode-prod-2",
    "datanode-prod-4",
    "rabbitmq-1",
    "redis-cache-master",
    "postgres-replica-1",
    "prometheus-collector",
)

DEFAULT_RATE = 10.0
DEFAULT_CRITICAL_FRACTION = 0.35
DEFAULT_INPUT = "training/data/openstack/openstack_abnormal.log"


@dataclass
class ReplayStats:
    """Lightweight observability for the CLI summary on shutdown."""
    lines_emitted: int = 0
    batches_emitted: int = 0
    critical_batches: int = 0
    publish_failures: int = 0


# -- source-pool sampling --------------------------------------------------


def make_batch_source_picker(
    *,
    critical_fraction: float,
    rng: random.Random | None = None,
) -> callable[[], str]:
    """Return a callable that yields a source name on each call.

    Each call performs a single coin flip: with probability
    `critical_fraction`, picks a random source from CRITICAL_SOURCES;
    otherwise picks from NON_CRITICAL_SOURCES. Both pools rotate via
    independent shuffled iterators so consecutive batches don't
    repeat the same hostname.
    """
    if not 0.0 <= critical_fraction <= 1.0:
        raise ValueError("critical_fraction must be in [0, 1]")
    rng = rng or random.Random()
    crit_iter = _shuffled_cycle(CRITICAL_SOURCES, rng)
    non_iter = _shuffled_cycle(NON_CRITICAL_SOURCES, rng)

    def pick() -> str:
        if rng.random() < critical_fraction:
            return next(crit_iter)
        return next(non_iter)

    return pick


def _shuffled_cycle(items: Iterable[str], rng: random.Random):
    """Yield items in shuffled order forever — re-shuffle every cycle so
    consecutive runs don't follow the same pattern."""
    pool = list(items)
    while True:
        rng.shuffle(pool)
        yield from pool


# -- file iteration --------------------------------------------------------


async def _iter_lines(path: Path, *, loop: bool, max_lines: int | None) -> AsyncIterator[str]:
    """Async generator over log lines from `path`. Empty / whitespace-only
    lines are skipped (the consumer's parser would reject them anyway).
    Loops forever if `loop=True`."""
    emitted = 0
    while True:
        with path.open("r", encoding="utf-8", errors="replace") as f:
            for raw in f:
                line = raw.rstrip("\n").rstrip("\r")
                if not line.strip():
                    continue
                yield line
                emitted += 1
                if max_lines is not None and emitted >= max_lines:
                    return
        if not loop:
            return


# -- core replay loop ------------------------------------------------------


async def replay(
    redis_client: redis_aio.Redis,
    *,
    input_path: Path,
    stream: str,
    rate: float,
    loop: bool,
    max_lines: int | None,
    critical_fraction: float,
    batch_size: int = WINDOW_SIZE,
    rng: random.Random | None = None,
) -> ReplayStats:
    """Replay `input_path` into Redis stream `stream`.

    Each `batch_size` consecutive lines are tagged with one source so
    the consumer's WindowBuilder produces source-coherent windows
    (otherwise window.source = 'mixed' and the critical tier never
    fires).
    """
    if rate <= 0:
        raise ValueError("rate must be positive")
    if batch_size < 1:
        raise ValueError("batch_size must be >= 1")
    if not input_path.exists():
        raise FileNotFoundError(f"input file not found: {input_path}")

    pick_source = make_batch_source_picker(
        critical_fraction=critical_fraction, rng=rng
    )

    inter_line_delay = 1.0 / rate
    stats = ReplayStats()
    current_source: str | None = None
    in_batch = 0

    async for line in _iter_lines(input_path, loop=loop, max_lines=max_lines):
        # Start a new batch every `batch_size` lines so consecutive
        # windows have a coherent source.
        if in_batch == 0:
            current_source = pick_source()
            stats.batches_emitted += 1
            if current_source in CRITICAL_SOURCES:
                stats.critical_batches += 1
        try:
            await redis_client.xadd(
                stream,
                {FIELD_LINE: line, FIELD_SOURCE: current_source or "unknown"},
            )
            stats.lines_emitted += 1
        except Exception:  # noqa: BLE001
            log.exception("xadd failed for line %d", stats.lines_emitted + 1)
            stats.publish_failures += 1

        in_batch = (in_batch + 1) % batch_size
        await asyncio.sleep(inter_line_delay)

    return stats


# -- CLI -------------------------------------------------------------------


def _arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Replay a log file into the LogGuard Redis stream for demo purposes.",
    )
    p.add_argument(
        "--input", type=Path,
        default=Path(os.environ.get("LOGGUARD_REPLAY_INPUT", DEFAULT_INPUT)),
        help="Log file to replay (default: %(default)s)",
    )
    p.add_argument(
        "--redis-url", type=str,
        default=os.environ.get("LOGGUARD_REDIS_URL", DEFAULT_REDIS_URL),
        help="Redis connection URL (default: %(default)s)",
    )
    p.add_argument(
        "--stream", type=str,
        default=os.environ.get("LOGGUARD_INGEST_STREAM", DEFAULT_STREAM),
        help="Redis stream name (default: %(default)s)",
    )
    p.add_argument(
        "--rate", type=float, default=DEFAULT_RATE,
        help="Lines per second (default: %(default)s)",
    )
    p.add_argument(
        "--max-lines", type=int, default=None,
        help="Stop after this many lines (default: replay the whole file)",
    )
    p.add_argument(
        "--loop", action="store_true",
        help="When the file ends, restart from the top forever.",
    )
    p.add_argument(
        "--critical-fraction", type=float, default=DEFAULT_CRITICAL_FRACTION,
        help=("Probability that each batch is tagged with a critical source "
              "(default: %(default)s, range 0..1)."),
    )
    p.add_argument(
        "--batch-size", type=int, default=WINDOW_SIZE,
        help=("Lines per source-batch (default: WINDOW_SIZE=%(default)s); "
              "every Nth line picks a fresh source."),
    )
    p.add_argument(
        "--seed", type=int, default=None,
        help="Random seed for reproducible source rotation (default: nondeterministic)",
    )
    return p


async def _run_cli(argv: list[str] | None = None) -> int:  # pragma: no cover — interactive runner
    args = _arg_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    log.info(
        "starting replay: input=%s stream=%s rate=%s/s critical=%s batch=%s loop=%s",
        args.input, args.stream, args.rate, args.critical_fraction, args.batch_size, args.loop,
    )

    rng = random.Random(args.seed) if args.seed is not None else None
    client: Any = redis_aio.from_url(args.redis_url, decode_responses=True)
    try:
        await client.ping()
    except Exception as e:  # noqa: BLE001
        log.error("cannot reach Redis at %s: %s", args.redis_url, e)
        await client.aclose()
        return 1

    try:
        stats = await replay(
            client,
            input_path=args.input,
            stream=args.stream,
            rate=args.rate,
            loop=args.loop,
            max_lines=args.max_lines,
            critical_fraction=args.critical_fraction,
            batch_size=args.batch_size,
            rng=rng,
        )
    except asyncio.CancelledError:
        log.info("replay cancelled")
        return 0
    finally:
        await client.aclose()

    log.info(
        "done. emitted=%d batches=%d (%d critical, %.0f%%) failures=%d",
        stats.lines_emitted,
        stats.batches_emitted,
        stats.critical_batches,
        100.0 * stats.critical_batches / max(stats.batches_emitted, 1),
        stats.publish_failures,
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(asyncio.run(_run_cli()))
