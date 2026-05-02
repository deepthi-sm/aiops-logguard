"""
Operator-only one-shot: re-tag historical anomalies under the new severity rules.

This script is **NOT auto-invoked**. Nothing in the live pipeline runs it.
It exists so that, if you choose to clean up the demo data after Review 3,
you can collapse the entire history under the current `decide_severity`
contract without spinning up the runner + replay to regenerate from scratch.

What "the new rules" means here:

  critical  if  ensemble_score > 0.85 AND source in critical_sources
  warning   if  ensemble_score > 0.75
  info      otherwise

(See `backend/ml/postprocess.py` `decide_severity` for the source of truth.)

Why it isn't auto-run:

  * Backfill rewrites history. Anomalies were tagged at the time they were
    written, under the rules that were in effect then. Silently mutating
    those rows would erase the audit trail of what severity the operator
    *actually saw* on the dashboard.
  * The runner-driven demo populates fresh rows under the new rules
    quickly via `tools.log_replay`, so for most cases the right move is
    "let new data flow in" rather than "rewrite the past."
  * Misconfigured critical-sources env or out-of-date thresholds would
    propagate silently across thousands of rows.

Usage (run from `backend/`):

    .venv/Scripts/python.exe -m scripts.backfill_severity --dry-run
    .venv/Scripts/python.exe -m scripts.backfill_severity --apply

Flags:

    --dry-run     Default. Prints the count of rows whose severity *would*
                  change, broken down by (current, new) pair. Writes nothing.
    --apply       Actually write the new severity values back to Postgres.
                  Required to make any real change.
    --db-url URL  Override LOGGUARD_DB_URL (default: env var, then
                  postgresql://postgres:postgres@localhost:5432/logguard).
    --critical-sources LIST
                  Comma-separated override for the critical-source set used
                  during retagging. Default reads from the LOGGUARD_CRITICAL
                  env var, then falls back to `DEFAULT_CRITICAL_SOURCES`
                  per `ml.postprocess.get_critical_sources`.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from collections import Counter
from dataclasses import dataclass

import asyncpg

# Make UTF-8-clean stdout/stderr on Windows cp1252 consoles.
for _stream in (sys.stdout, sys.stderr):
    try:
        if _stream.encoding != "utf-8":
            _stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except (AttributeError, ValueError):
        pass

# Imports below the stream reconfig must wait until after stdout/stderr
# are UTF-8-clean — `ml.postprocess` indirectly imports torch via the
# detector chain, and torch's lazy CUDA-init prints can crash the
# console on cp1252. E402 is the documented trade-off here.
from ml.postprocess import (  # noqa: E402
    CRITICAL_ENSEMBLE_SCORE,
    WARNING_ENSEMBLE_SCORE,
    get_critical_sources,
)

DEFAULT_DB_URL = "postgresql://postgres:postgres@localhost:5432/logguard"


@dataclass(frozen=True)
class Row:
    """Just the columns the severity rule needs."""
    id: str
    severity: str
    source: str
    ensemble_score: float


def _new_severity(row: Row, critical_sources: frozenset[str]) -> str:
    """Pure function — same shape as `ml.postprocess.decide_severity`,
    but takes a Row instead of a DetectionResult so we can apply it to
    DB records that don't carry the full DetectionResult tuple."""
    if (
        row.ensemble_score > CRITICAL_ENSEMBLE_SCORE
        and row.source in critical_sources
    ):
        return "critical"
    if row.ensemble_score > WARNING_ENSEMBLE_SCORE:
        return "warning"
    return "info"


async def _fetch_rows(pool: asyncpg.Pool) -> list[Row]:
    async with pool.acquire() as conn:
        records = await conn.fetch(
            "SELECT id, severity, source, ensemble_score FROM anomalies"
        )
    return [
        Row(
            id=r["id"],
            severity=r["severity"],
            source=r["source"],
            ensemble_score=float(r["ensemble_score"] or 0.0),
        )
        for r in records
    ]


async def _apply_changes(pool: asyncpg.Pool, changes: list[tuple[str, str]]) -> int:
    """Write `(new_severity, id)` pairs back to Postgres in one batch.
    Returns the number of rows actually updated."""
    if not changes:
        return 0
    async with pool.acquire() as conn:
        await conn.executemany(
            "UPDATE anomalies SET severity = $1 WHERE id = $2",
            changes,
        )
    return len(changes)


def _print_diff(rows: list[Row], critical_sources: frozenset[str]) -> tuple[
    list[tuple[str, str]], Counter
]:
    """Compute the diff and print a human-readable summary.
    Returns the (id, new_severity) update list + a (current, new) counter."""
    changes: list[tuple[str, str]] = []  # (new_severity, id) — order matches asyncpg arg order
    transitions: Counter[tuple[str, str]] = Counter()
    by_new: Counter[str] = Counter()

    for r in rows:
        new = _new_severity(r, critical_sources)
        by_new[new] += 1
        if new != r.severity:
            transitions[(r.severity, new)] += 1
            changes.append((new, r.id))

    print(f"Total rows scanned: {len(rows):,}")
    print()
    print("New severity distribution (under the current rules):")
    for sev in ("critical", "warning", "info"):
        print(f"  {sev:<9}  {by_new.get(sev, 0):>7,}")
    print()
    if not transitions:
        print("No rows would change severity. Nothing to do.")
        return changes, transitions
    print(f"{sum(transitions.values()):,} row(s) would change severity:")
    for (old, new), n in sorted(transitions.items()):
        print(f"  {old:<8} -> {new:<8}  {n:>7,}")
    print()
    return changes, transitions


async def main_async(args: argparse.Namespace) -> int:
    db_url = args.db_url or os.environ.get("LOGGUARD_DB_URL", DEFAULT_DB_URL)

    if args.critical_sources:
        critical_sources = frozenset(
            s.strip() for s in args.critical_sources.split(",") if s.strip()
        )
    else:
        critical_sources = get_critical_sources()
    print(f"Using critical_sources: {sorted(critical_sources)}")
    print()

    pool = await asyncpg.create_pool(db_url, min_size=1, max_size=2)
    try:
        rows = await _fetch_rows(pool)
        changes, transitions = _print_diff(rows, critical_sources)
        if args.apply and changes:
            n = await _apply_changes(pool, changes)
            print(f"APPLIED: updated {n:,} rows.")
        elif changes:
            print("DRY RUN: no changes written. Re-run with --apply to commit.")
    finally:
        await pool.close()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Backfill anomaly severity under the current decide_severity rules.",
    )
    parser.add_argument("--db-url", default=None, help="Override LOGGUARD_DB_URL.")
    parser.add_argument(
        "--critical-sources", default=None,
        help="Comma-separated override for the critical-source set.",
    )
    grp = parser.add_mutually_exclusive_group()
    grp.add_argument(
        "--dry-run", action="store_true", default=True,
        help="Show what would change without writing (DEFAULT).",
    )
    grp.add_argument(
        "--apply", action="store_true",
        help="Write the new severities back to Postgres.",
    )
    args = parser.parse_args()
    if args.apply:
        args.dry_run = False
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    sys.exit(main())
