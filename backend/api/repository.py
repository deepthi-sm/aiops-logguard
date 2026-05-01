"""
SQL-layer queries for the public API.

Keeps the route handlers in `api.routes` free of SQL — handlers express
the contract (filters, pagination, schema mapping) and call into here
when they need to read/write the database. asyncpg returns `Record`
objects we hydrate into the canonical Pydantic models.

A note on JSONB columns: asyncpg returns JSONB as Python text, not as
parsed JSON. We register a JSONB codec on each pool acquisition so
`row["sequence_preview"]` is already a list, not a string. See
`hydrate_anomaly()` for the resulting shape.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

import asyncpg

from api.schemas import (
    Anomaly,
    ContributingLine,
    DriftStatus,
    Explanation,
    MetricsSummary,
    Severity,
    SimilarIncident,
    TimelineBucket,
    TimelineResponse,
    TimelineWindow,
)

# -- JSONB codec ------------------------------------------------------------


async def install_jsonb_codec(conn: asyncpg.Connection) -> None:
    """Register a JSONB codec so list/dict columns deserialize automatically.

    asyncpg's default leaves JSONB as a string; we'd otherwise have to
    json.loads() at every read site. Run this on each new pool's
    connection-init hook (see `api.main`'s lifespan).
    """
    await conn.set_type_codec(
        "jsonb",
        encoder=json.dumps,
        decoder=json.loads,
        schema="pg_catalog",
    )


# -- hydration helpers ------------------------------------------------------


def hydrate_anomaly(row: asyncpg.Record) -> Anomaly:
    """Map an `anomalies` row to the public Anomaly schema.

    `sequence_preview`, `top_contributing_lines`, and `similar_incidents`
    are JSONB columns — codec already converts them to Python objects.
    """
    contributing = [
        ContributingLine(line=item["line"], attention=float(item["attention"]))
        for item in (row["top_contributing_lines"] or [])
    ]
    return Anomaly(
        id=row["id"],
        detected_at=row["detected_at"],
        severity=row["severity"],
        source=row["source"],
        ensemble_score=float(row["ensemble_score"] or 0.0),
        confidence=float(row["confidence"] or 0.0),
        failure_probability=float(row["failure_probability"] or 0.0),
        predicted_failure_window_min=row["predicted_failure_window_min"],
        log_template=row["log_template"] or "",
        sequence_preview=list(row["sequence_preview"] or []),
        top_contributing_lines=contributing,
        explanation_status=row["explanation_status"],
        cluster_id=row["cluster_id"] or "",
        cluster_size=int(row["cluster_size"] or 1),
    )


def hydrate_explanation(row: asyncpg.Record) -> Explanation | None:
    """Build an Explanation from a row — None if the RAG worker hasn't
    populated `root_cause` yet (status `pending`)."""
    if row["root_cause"] is None and row["recommended_fix"] is None:
        return None
    similar = [
        SimilarIncident(
            incident_id=item["incident_id"],
            template=item["template"],
            resolved_at=_parse_iso(item.get("resolved_at")),
            similarity_score=float(item["similarity_score"]),
        )
        for item in (row["similar_incidents"] or [])
    ]
    # `attention_weights` isn't a column today — derive from
    # top_contributing_lines for now. When the RAG worker stores its own
    # attention vector we can switch to that.
    weights = [
        float(item["attention"])
        for item in (row["top_contributing_lines"] or [])
    ]
    return Explanation(
        root_cause=row["root_cause"] or "",
        recommended_fix=row["recommended_fix"] or "",
        similar_incidents=similar,
        attention_weights=weights,
    )


def _parse_iso(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


# -- anomaly queries --------------------------------------------------------


async def list_anomalies(
    pool: asyncpg.Pool,
    *,
    limit: int,
    offset: int,
    severity: Severity | None,
    since: datetime | None,
) -> tuple[list[Anomaly], int]:
    """Return `(items, total_matching_count)` so the route can compute
    the next pagination cursor without a second round-trip."""
    where_clauses: list[str] = []
    args: list[Any] = []
    if severity is not None:
        args.append(severity)
        where_clauses.append(f"severity = ${len(args)}")
    if since is not None:
        args.append(since)
        where_clauses.append(f"detected_at > ${len(args)}")
    where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

    count_sql = f"SELECT COUNT(*) FROM anomalies {where_sql}"
    list_sql = (
        f"SELECT * FROM anomalies {where_sql} "
        f"ORDER BY detected_at DESC "
        f"LIMIT ${len(args) + 1} OFFSET ${len(args) + 2}"
    )

    async with pool.acquire() as conn:
        total = await conn.fetchval(count_sql, *args)
        rows = await conn.fetch(list_sql, *args, limit, offset)
    return [hydrate_anomaly(r) for r in rows], int(total or 0)


async def get_anomaly(pool: asyncpg.Pool, anomaly_id: str) -> Anomaly | None:
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM anomalies WHERE id = $1", anomaly_id
        )
    return hydrate_anomaly(row) if row is not None else None


async def get_explanation(
    pool: asyncpg.Pool,
    anomaly_id: str,
) -> tuple[str | None, Explanation | None]:
    """Returns `(explanation_status, explanation_or_none)`. Status is
    None when the row doesn't exist (route turns this into 404)."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT explanation_status, root_cause, recommended_fix, "
            "similar_incidents, top_contributing_lines "
            "FROM anomalies WHERE id = $1",
            anomaly_id,
        )
    if row is None:
        return None, None
    return row["explanation_status"], hydrate_explanation(row)


async def insert_anomaly(pool: asyncpg.Pool, anomaly: Anomaly) -> None:
    """Insert one canonical Anomaly. Used by the live runner (Step 4b-iii)
    and by tests to seed the table. Idempotent on the primary key."""
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO anomalies (
                id, detected_at, severity, source,
                ensemble_score, confidence, failure_probability,
                predicted_failure_window_min,
                log_template, sequence_preview, top_contributing_lines,
                explanation_status, cluster_id, cluster_size
            ) VALUES (
                $1, $2, $3, $4,
                $5, $6, $7,
                $8,
                $9, $10, $11,
                $12, $13, $14
            )
            ON CONFLICT (id) DO NOTHING
            """,
            anomaly.id,
            anomaly.detected_at,
            anomaly.severity,
            anomaly.source,
            anomaly.ensemble_score,
            anomaly.confidence,
            anomaly.failure_probability,
            anomaly.predicted_failure_window_min,
            anomaly.log_template,
            list(anomaly.sequence_preview),
            [c.model_dump(mode="json") for c in anomaly.top_contributing_lines],
            anomaly.explanation_status,
            anomaly.cluster_id,
            anomaly.cluster_size,
        )


async def update_explanation(
    pool: asyncpg.Pool,
    anomaly_id: str,
    *,
    root_cause: str,
    recommended_fix: str,
    similar_incidents: list[SimilarIncident],
    status: str = "ready",
) -> bool:
    """Used by the RAG worker (Step 5). Returns True if a row was updated."""
    async with pool.acquire() as conn:
        result = await conn.execute(
            """
            UPDATE anomalies
            SET root_cause = $2,
                recommended_fix = $3,
                similar_incidents = $4,
                explanation_status = $5
            WHERE id = $1
            """,
            anomaly_id,
            root_cause,
            recommended_fix,
            [s.model_dump(mode="json") for s in similar_incidents],
            status,
        )
    return result.endswith(" 1")


async def record_feedback(
    pool: asyncpg.Pool,
    anomaly_id: str,
    feedback: str,
) -> bool:
    """Update `feedback` column on the anomaly. Returns True if a row was updated."""
    async with pool.acquire() as conn:
        result = await conn.execute(
            "UPDATE anomalies SET feedback = $2 WHERE id = $1",
            anomaly_id,
            feedback,
        )
    return result.endswith(" 1")


# -- metrics queries --------------------------------------------------------


async def metrics_summary(pool: asyncpg.Pool) -> MetricsSummary:
    """Top-line KPIs — used by the dashboard's KPI strip.

    The schema doesn't have a separate drift table snapshot we can
    query for `drift_score` and `last_retrain` here; those come from
    `drift_status()` and the `training_runs` table respectively. For
    now we surface zeros + null for last_retrain and let the runner
    in 4b-iii backfill drift_score during a live demo.
    """
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT
              COUNT(*) FILTER (WHERE detected_at > NOW() - INTERVAL '24 hours') AS total_24h,
              COUNT(*) FILTER (
                WHERE detected_at > NOW() - INTERVAL '24 hours' AND severity = 'critical'
              ) AS critical_24h,
              COUNT(*) FILTER (
                WHERE detected_at > NOW() - INTERVAL '24 hours' AND severity = 'warning'
              ) AS warning_24h,
              COUNT(*) FILTER (
                WHERE detected_at > NOW() - INTERVAL '24 hours' AND severity = 'info'
              ) AS info_24h,
              COALESCE(
                AVG(confidence) FILTER (WHERE detected_at > NOW() - INTERVAL '24 hours'),
                0
              ) AS avg_confidence
            FROM anomalies
            """
        )
        last_retrain = await conn.fetchval(
            "SELECT MAX(completed_at) FROM training_runs"
        )
        drift = await conn.fetchrow(
            "SELECT psi_score FROM drift_events ORDER BY detected_at DESC LIMIT 1"
        )

    return MetricsSummary(
        total_24h=int(row["total_24h"] or 0),
        critical_24h=int(row["critical_24h"] or 0),
        warning_24h=int(row["warning_24h"] or 0),
        info_24h=int(row["info_24h"] or 0),
        avg_confidence=round(float(row["avg_confidence"] or 0.0), 3),
        drift_score=float(drift["psi_score"]) if drift else 0.0,
        last_retrain=last_retrain,
    )


_TIMELINE_CONFIG: dict[TimelineWindow, tuple[int, timedelta]] = {
    "1h": (60, timedelta(minutes=1)),
    "24h": (96, timedelta(minutes=15)),
    "7d": (168, timedelta(hours=1)),
}


async def metrics_timeline(
    pool: asyncpg.Pool, window: TimelineWindow
) -> TimelineResponse:
    """Bucketed counts by severity. Bucket sizes per the contract:
    1h → 60×1m, 24h → 96×15m, 7d → 168×1h."""
    bucket_count, bucket_step = _TIMELINE_CONFIG[window]
    end = datetime.now(UTC).replace(microsecond=0)
    start = end - bucket_step * (bucket_count - 1)

    # `time_bucket` would be ideal but isn't in vanilla Postgres — use
    # date_trunc-equivalent via floor-divide. We compute the floor in
    # Python and pass an array of bucket starts to the SQL via UNNEST.
    bucket_starts = [start + bucket_step * i for i in range(bucket_count)]

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            WITH buckets AS (
                SELECT unnest($1::timestamptz[]) AS bucket_start,
                       unnest($1::timestamptz[]) + $2::interval AS bucket_end
            )
            SELECT
                b.bucket_start AS ts,
                COUNT(*) FILTER (WHERE a.severity = 'critical') AS critical,
                COUNT(*) FILTER (WHERE a.severity = 'warning') AS warning,
                COUNT(*) FILTER (WHERE a.severity = 'info') AS info
            FROM buckets b
            LEFT JOIN anomalies a
                   ON a.detected_at >= b.bucket_start
                  AND a.detected_at <  b.bucket_end
            GROUP BY b.bucket_start
            ORDER BY b.bucket_start
            """,
            bucket_starts,
            bucket_step,
        )

    buckets = [
        TimelineBucket(
            ts=r["ts"],
            critical=int(r["critical"] or 0),
            warning=int(r["warning"] or 0),
            info=int(r["info"] or 0),
        )
        for r in rows
    ]
    return TimelineResponse(window=window, buckets=buckets)


# -- drift ------------------------------------------------------------------


async def drift_status(pool: asyncpg.Pool) -> DriftStatus:
    """Most recent drift event + last retrain. Returns a healthy default
    when no drift events have been recorded yet (fresh DB)."""
    async with pool.acquire() as conn:
        drift_row = await conn.fetchrow(
            "SELECT psi_score, severity FROM drift_events "
            "ORDER BY detected_at DESC LIMIT 1"
        )
        last_retrain = await conn.fetchval(
            "SELECT MAX(completed_at) FROM training_runs"
        )

    if drift_row is None:
        return DriftStatus(
            drift_score=0.0,
            last_retrain=last_retrain,
            status="healthy",
            psi_score=0.0,
        )
    psi = float(drift_row["psi_score"])
    severity = drift_row["severity"]  # 'drift_high' | 'drift_critical'
    return DriftStatus(
        drift_score=psi,
        last_retrain=last_retrain,
        status=severity,
        psi_score=psi,
    )
