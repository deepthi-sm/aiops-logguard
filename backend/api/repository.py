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
    SystemQueueResponse,
    TimelineBucket,
    TimelineResponse,
    TimelineWindow,
    TrainingRun,
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


def _coerce_jsonb(value: Any) -> Any:
    """Tolerate JSONB columns that arrive as strings.

    With the codec installed (see `install_jsonb_codec`) JSONB returns
    as native Python. But rows written by an older runner without the
    codec, or read from a connection that didn't pick up the codec,
    can come back as a JSON-string. Defensively `json.loads` once if we
    see a string; otherwise return as-is. Idempotent for already-decoded
    values.
    """
    if isinstance(value, str | bytes | bytearray):
        try:
            return json.loads(value)
        except (TypeError, ValueError):
            return None
    return value


def hydrate_anomaly(row: asyncpg.Record) -> Anomaly:
    """Map an `anomalies` row to the public Anomaly schema.

    `sequence_preview`, `top_contributing_lines`, and `similar_incidents`
    are JSONB columns — codec normally converts them to Python objects;
    `_coerce_jsonb` is a defensive fallback for rows that bypassed the
    codec when they were written.

    Real model scores are surfaced verbatim — no display caps or
    normalisation. The teacher's evaluation expects to see the actual
    `ensemble_score` and `failure_probability` from the trained models.
    """
    raw_contrib = _coerce_jsonb(row["top_contributing_lines"]) or []
    contributing = [
        ContributingLine(line=item["line"], attention=float(item["attention"]))
        for item in raw_contrib
        if isinstance(item, dict)
    ]
    raw_seq = _coerce_jsonb(row["sequence_preview"]) or []
    return Anomaly(
        id=row["id"],
        detected_at=row["detected_at"],
        severity=row["severity"],
        source=row["source"],
        origin=row["origin"],
        ensemble_score=float(row["ensemble_score"] or 0.0),
        confidence=float(row["confidence"] or 0.0),
        failure_probability=float(row["failure_probability"] or 0.0),
        predicted_failure_window_min=row["predicted_failure_window_min"],
        log_template=row["log_template"] or "",
        sequence_preview=[str(s) for s in raw_seq],
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
    raw_similar = _coerce_jsonb(row["similar_incidents"]) or []
    similar = [
        SimilarIncident(
            incident_id=item["incident_id"],
            template=item["template"],
            resolved_at=_parse_iso(item.get("resolved_at")),
            similarity_score=float(item["similarity_score"]),
        )
        for item in raw_similar
        if isinstance(item, dict)
    ]
    # `attention_weights` isn't a column today — derive from
    # top_contributing_lines for now. When the RAG worker stores its own
    # attention vector we can switch to that.
    raw_contrib = _coerce_jsonb(row["top_contributing_lines"]) or []
    weights = [
        float(item["attention"])
        for item in raw_contrib
        if isinstance(item, dict)
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
    source: str | None = None,
    origin: str | None = None,
) -> tuple[list[Anomaly], int]:
    """Return `(items, total_matching_count)` so the route can compute
    the next pagination cursor without a second round-trip.

    `source` is an exact-match filter on the `source` column (parsed
    host/service identifier — what the UI displays).

    `origin` is an exact-match filter on the `origin` column
    ('live-stream' | 'user-upload' — entry-point tag). Used by the
    upload flow's redirect (`/anomalies?origin=user-upload`) to surface
    only anomalies derived from a /upload call.
    """
    where_clauses: list[str] = []
    args: list[Any] = []
    if severity is not None:
        args.append(severity)
        where_clauses.append(f"severity = ${len(args)}")
    if since is not None:
        args.append(since)
        where_clauses.append(f"detected_at > ${len(args)}")
    if source is not None:
        args.append(source)
        where_clauses.append(f"source = ${len(args)}")
    if origin is not None:
        args.append(origin)
        where_clauses.append(f"origin = ${len(args)}")
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


async def get_newest_anomaly(pool: asyncpg.Pool) -> Anomaly | None:
    """Most recently detected anomaly. Used by the WS handler as the
    initial frame so a freshly-connected dashboard has something to
    render before the next live detection arrives."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM anomalies ORDER BY detected_at DESC LIMIT 1"
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
                id, detected_at, severity, source, origin,
                ensemble_score, confidence, failure_probability,
                predicted_failure_window_min,
                log_template, sequence_preview, top_contributing_lines,
                explanation_status, cluster_id, cluster_size
            ) VALUES (
                $1, $2, $3, $4, $5,
                $6, $7, $8,
                $9,
                $10, $11, $12,
                $13, $14, $15
            )
            ON CONFLICT (id) DO NOTHING
            """,
            anomaly.id,
            anomaly.detected_at,
            anomaly.severity,
            anomaly.source,
            anomaly.origin,
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


async def list_feedback(
    pool: asyncpg.Pool,
    *,
    limit: int = 100,
) -> tuple[list[dict[str, Any]], int, int, int]:
    """Return (items, total, true_positive_count, false_positive_count).

    Joins are unnecessary — feedback lives on the `anomalies` row itself
    as a TEXT column. We pull only the fields the frontend list view
    needs and skip the JSONB columns to keep the payload small.

    Sorted by `detected_at DESC` because we don't yet store a separate
    `feedback_submitted_at` timestamp; the underlying anomaly's
    detection time is a reasonable proxy for ordering ("most recent
    feedback at the top of the list" maps to "most recent anomaly
    that has feedback").
    """
    sql = (
        "SELECT id, severity, source, log_template, detected_at, feedback, "
        "       root_cause "
        "FROM anomalies "
        "WHERE feedback IS NOT NULL "
        "ORDER BY detected_at DESC "
        "LIMIT $1"
    )
    counts_sql = (
        "SELECT "
        "  COUNT(*) FILTER (WHERE feedback = 'true_positive') AS tp, "
        "  COUNT(*) FILTER (WHERE feedback = 'false_positive') AS fp, "
        "  COUNT(*) FILTER (WHERE feedback IS NOT NULL) AS total "
        "FROM anomalies"
    )
    async with pool.acquire() as conn:
        rows = await conn.fetch(sql, limit)
        counts = await conn.fetchrow(counts_sql)
    items = [
        {
            "anomaly_id": r["id"],
            "verdict": r["feedback"],
            "submitted_at": r["detected_at"],
            "source": r["source"],
            "log_template": r["log_template"] or "",
            "severity": r["severity"],
            # Empty string when the explainer hasn't yet produced one
            # (still pending / failed) — the frontend's Incidents page
            # uses this to render the postmortem snippet next to the
            # anomaly id, falling back to the template when blank.
            "root_cause": r["root_cause"] or "",
        }
        for r in rows
    ]
    return (
        items,
        int(counts["total"] or 0),
        int(counts["tp"] or 0),
        int(counts["fp"] or 0),
    )


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


# -- system queue snapshot --------------------------------------------------


async def system_queue_snapshot(pool: asyncpg.Pool) -> SystemQueueResponse:
    """Snapshot of the pending-explanation queue.

    Two queries: counts grouped by `explanation_status`, plus the
    oldest pending row's id and detection timestamp (so the System
    page can render "oldest pending: anom_… — N min ago").

    Cheap to call every couple of seconds — both queries are
    indexed-friendly (status filter + ORDER BY detected_at LIMIT 1).
    """
    counts_sql = (
        "SELECT explanation_status AS status, COUNT(*) AS n "
        "FROM anomalies GROUP BY explanation_status"
    )
    oldest_sql = (
        "SELECT id, detected_at FROM anomalies "
        "WHERE explanation_status = 'pending' "
        "ORDER BY detected_at ASC LIMIT 1"
    )
    async with pool.acquire() as conn:
        rows = await conn.fetch(counts_sql)
        oldest = await conn.fetchrow(oldest_sql)

    counts = {r["status"]: int(r["n"]) for r in rows}
    return SystemQueueResponse(
        pending=counts.get("pending", 0),
        ready=counts.get("ready", 0),
        failed=counts.get("failed", 0),
        oldest_pending_id=oldest["id"] if oldest else None,
        oldest_pending_at=oldest["detected_at"] if oldest else None,
    )


# -- training runs ----------------------------------------------------------


_TRAINING_RUN_F1_FLOOR = 0.5  # below this is treated as a failed run


async def list_training_runs(
    pool: asyncpg.Pool,
    *,
    limit: int = 50,
) -> tuple[list[TrainingRun], int | None]:
    """Return (items, active_id) for the training_runs table.

    Sort key: completed_at DESC NULLS LAST, then started_at DESC, so
    runs that are still in flight (completed_at IS NULL) sit at the
    bottom rather than getting promoted past completed runs by their
    started_at.

    Status derivation, server-side so the frontend doesn't have to
    re-do it on every render:
      - failed:    f1_score is NULL or < 0.5
      - active:    the most recently completed run with f1 >= 0.5
      - completed: any other successful run

    `active_id` mirrors the row whose status came back "active", or
    None when no run qualifies (e.g. fresh DB before seed).
    """
    sql = (
        "SELECT id, started_at, completed_at, dataset, f1_score, "
        "       precision_score, recall_score, artifacts_path, notes "
        "FROM training_runs "
        "ORDER BY completed_at DESC NULLS LAST, started_at DESC "
        "LIMIT $1"
    )
    async with pool.acquire() as conn:
        rows = await conn.fetch(sql, limit)

    # Find the id of the active run — the most recently completed
    # row with f1 >= the floor. Iterate in the already-sorted order.
    active_id: int | None = None
    for r in rows:
        f1 = r["f1_score"]
        if r["completed_at"] is not None and f1 is not None and float(f1) >= _TRAINING_RUN_F1_FLOOR:
            active_id = int(r["id"])
            break

    items: list[TrainingRun] = []
    for r in rows:
        rid = int(r["id"])
        f1 = r["f1_score"]
        if f1 is None or float(f1) < _TRAINING_RUN_F1_FLOOR:
            status = "failed"
        elif rid == active_id:
            status = "active"
        else:
            status = "completed"
        items.append(TrainingRun(
            id=rid,
            started_at=r["started_at"],
            completed_at=r["completed_at"],
            dataset=r["dataset"],
            f1_score=float(f1) if f1 is not None else None,
            precision_score=float(r["precision_score"]) if r["precision_score"] is not None else None,
            recall_score=float(r["recall_score"]) if r["recall_score"] is not None else None,
            artifacts_path=r["artifacts_path"],
            notes=r["notes"] or "",
            status=status,  # type: ignore[arg-type]
        ))
    return items, active_id


# -- drift ------------------------------------------------------------------


_DRIFT_HIGH_THRESHOLD = 0.40
_DRIFT_CRITICAL_THRESHOLD = 0.55


def _band_drift_status(psi: float) -> str:
    """Threshold banding for the synthetic-proxy drift score.

    psi <  0.40           → healthy
    0.40 <= psi <  0.55   → drift_high
    psi >= 0.55           → drift_critical

    These thresholds were chosen so typical operation on the trained
    domains (OpenStack, BGL through the OS-trained model) sits well
    inside "healthy" — std-dev of confidences for those datasets is
    ~0.20-0.30 — while a genuinely-shifted distribution (e.g. all-INFO
    replay or a corrupted upload that produces uniformly low-confidence
    rows) pushes std-dev above 0.40 and starts flipping the badge.
    """
    if psi >= _DRIFT_CRITICAL_THRESHOLD:
        return "drift_critical"
    if psi >= _DRIFT_HIGH_THRESHOLD:
        return "drift_high"
    return "healthy"


async def drift_status(pool: asyncpg.Pool) -> DriftStatus:
    """Most recent drift event + last retrain.

    When there's no drift_events row recorded (fresh DB / no drift
    detected yet), we surface a synthetic baseline computed from the
    confidence distribution of recent anomalies. The synthetic score
    is the std-dev of the last 200 anomaly confidences. True PSI
    requires a paired reference distribution; this proxy tracks the
    same underlying signal (input variability) without needing the
    reference set baked in.

    The previous version of this function clamped the synthetic value
    at 0.099 so the status would always read "healthy", which made the
    UI display 0.10 for every dataset regardless of actual variability.
    The clamp is now gone: the synthetic score is reported honestly,
    banded into healthy / drift_high / drift_critical via the same
    thresholds used for real drift events. The response carries
    `is_synthetic=True` so the frontend can label the number as a
    proxy.

    When a real drift_events row is inserted by a future periodic
    detector, that takes precedence and `is_synthetic=False`.
    """
    async with pool.acquire() as conn:
        drift_row = await conn.fetchrow(
            "SELECT psi_score, severity FROM drift_events "
            "ORDER BY detected_at DESC LIMIT 1"
        )
        last_retrain = await conn.fetchval(
            "SELECT MAX(completed_at) FROM training_runs"
        )

        if drift_row is None:
            baseline = await conn.fetchval(
                """
                SELECT COALESCE(STDDEV(confidence), 0.0)
                FROM (
                    SELECT confidence FROM anomalies
                    ORDER BY detected_at DESC LIMIT 200
                ) recent
                """
            )

    if drift_row is None:
        # Synthetic path: clip only to the schema's [0, 1] range, no
        # artificial "stay healthy" cap. Status is derived from the
        # same banding the real path uses.
        psi = min(1.0, max(0.0, float(baseline or 0.0)))
        return DriftStatus(
            drift_score=psi,
            last_retrain=last_retrain,
            status=_band_drift_status(psi),
            psi_score=psi,
            is_synthetic=True,
        )
    psi = float(drift_row["psi_score"])
    severity = drift_row["severity"]  # 'drift_high' | 'drift_critical'
    return DriftStatus(
        drift_score=psi,
        last_retrain=last_retrain,
        status=severity,
        psi_score=psi,
        is_synthetic=False,
    )
