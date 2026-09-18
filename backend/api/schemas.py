"""
Pydantic models — the integration contract with the frontend.

FastAPI generates openapi.json from these models. Person B's TypeScript
client is generated from that file. Changing a field here without bumping
the API version is a silent breaking change. See docs/architecture/api_contract.md.

Conventions enforced here (CLAUDE.md "Naming conventions"):
  * `severity` is exactly "critical" | "warning" | "info"
  * `explanation_status` is "pending" | "ready" | "failed"
  * All datetimes serialize as ISO 8601 UTC with a "Z" suffix (not "+00:00")
"""
from datetime import UTC, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field, PlainSerializer


def _to_iso_z(dt: datetime) -> str:
    """Serialize a datetime as ISO 8601 UTC with the trailing 'Z' suffix.

    Pydantic's default datetime serializer emits '+00:00' which is technically
    equivalent but visually inconsistent with the contract. Frontends sometimes
    parse them differently — pin the on-wire form so there's never a question.
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


# Reusable annotated datetime — use this in every schema field instead of bare datetime.
IsoUtcDatetime = Annotated[datetime, PlainSerializer(_to_iso_z, return_type=str)]


# ---------- Enums (closed sets) ----------

Severity = Literal["critical", "warning", "info"]
ExplanationStatus = Literal["pending", "ready", "failed"]
Feedback = Literal["true_positive", "false_positive"]
TimelineWindow = Literal["1h", "24h", "7d"]
DriftLevel = Literal["healthy", "drift_high", "drift_critical"]
# `origin` is the entry-point tag for filtering — distinct from `source`,
# which is the parsed host/service identifier displayed in the UI.
#   "live-stream"  → emitted by the live ingestion runner
#   "user-upload"  → emitted by a /upload streaming job
Origin = Literal["live-stream", "user-upload"]


# ---------- Health ----------

class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    version: str
    uptime_s: int = Field(ge=0)


# ---------- Anomaly ----------

class ContributingLine(BaseModel):
    line: str
    attention: float = Field(ge=0.0, le=1.0)


class Anomaly(BaseModel):
    id: str
    detected_at: IsoUtcDatetime
    severity: Severity
    source: str
    origin: Origin = "live-stream"
    ensemble_score: float = Field(ge=0.0, le=1.0)
    confidence: float = Field(ge=0.0, le=1.0)
    failure_probability: float = Field(ge=0.0, le=1.0)
    # Nullable when failure prediction doesn't apply (e.g. info-severity anomalies).
    predicted_failure_window_min: int | None = None
    log_template: str
    sequence_preview: list[str]
    top_contributing_lines: list[ContributingLine]
    explanation_status: ExplanationStatus
    cluster_id: str
    cluster_size: int = Field(ge=1)


class AnomalyListResponse(BaseModel):
    items: list[Anomaly]
    next_cursor: str | None = None


# ---------- Explanation ----------

class SimilarIncident(BaseModel):
    incident_id: str
    template: str
    resolved_at: IsoUtcDatetime | None = None
    similarity_score: float = Field(ge=0.0, le=1.0)


class Explanation(BaseModel):
    root_cause: str
    recommended_fix: str
    similar_incidents: list[SimilarIncident]
    attention_weights: list[float]


# ---------- Metrics ----------

class MetricsSummary(BaseModel):
    total_24h: int = Field(ge=0)
    critical_24h: int = Field(ge=0)
    warning_24h: int = Field(ge=0)
    info_24h: int = Field(ge=0)
    avg_confidence: float = Field(ge=0.0, le=1.0)
    drift_score: float = Field(ge=0.0)
    last_retrain: IsoUtcDatetime | None = None


class TimelineBucket(BaseModel):
    ts: IsoUtcDatetime
    critical: int = Field(ge=0)
    warning: int = Field(ge=0)
    info: int = Field(ge=0)


class TimelineResponse(BaseModel):
    window: TimelineWindow
    buckets: list[TimelineBucket]


# ---------- Drift ----------

class DriftStatus(BaseModel):
    drift_score: float = Field(ge=0.0)
    last_retrain: IsoUtcDatetime | None = None
    status: DriftLevel
    psi_score: float = Field(ge=0.0)
    # Additive optional flag (default False): True when the score is a
    # synthetic proxy (std-dev of recent confidences) rather than a
    # real PSI from a `drift_events` row. Lets the frontend render a
    # "synthetic indicator" subtext without breaking older clients
    # that don't read this field.
    is_synthetic: bool = False


# ---------- Feedback ----------

class FeedbackRequest(BaseModel):
    feedback: Feedback


class FeedbackResponse(BaseModel):
    ok: bool


class FeedbackHistoryItem(BaseModel):
    """One row of feedback history. Fields are denormalised from the
    `anomalies` table so the frontend can render the list without
    follow-up GETs per anomaly."""
    anomaly_id: str
    verdict: Feedback
    submitted_at: IsoUtcDatetime  # proxied by detected_at; we don't yet
                                  # store a separate feedback timestamp.
    source: str
    log_template: str
    severity: Severity
    # Postmortem snippet from the RAG worker. Empty string when the
    # explainer hasn't run yet for this anomaly (status != "ready");
    # the Incidents page falls back to log_template when blank.
    # Additive optional field with default "" so older API consumers
    # that don't read it stay compatible.
    root_cause: str = ""


class FeedbackHistoryResponse(BaseModel):
    """GET /api/v1/feedback. Newest first; capped by `limit`."""
    items: list[FeedbackHistoryItem]
    total: int = Field(ge=0)
    true_positive: int = Field(ge=0)
    false_positive: int = Field(ge=0)


# ---------- System services + queue (GET /api/v1/system/services etc.) ----

ServiceStatus = Literal["online", "degraded", "offline"]


class SystemService(BaseModel):
    """One row in the System page's services grid. `status` is the
    live probe outcome; `detail` is a short human-readable line shown
    under the name."""
    name: str
    status: ServiceStatus
    detail: str


class SystemServicesResponse(BaseModel):
    items: list[SystemService]


class SystemQueueResponse(BaseModel):
    """Snapshot of the pending-explanation queue. Lets the System page
    show "is the RAG worker keeping up?" without instrumenting the
    worker itself."""
    pending: int = Field(ge=0)
    ready: int = Field(ge=0)
    failed: int = Field(ge=0)
    oldest_pending_id: str | None = None
    oldest_pending_at: IsoUtcDatetime | None = None


# ---------- Training runs (GET /api/v1/training/runs) ----------

TrainingRunStatus = Literal["active", "completed", "failed"]


class TrainingRun(BaseModel):
    """One row of `training_runs`. Mirrors the table 1:1 plus a derived
    `status` field — "active" for the most-recently-completed run with
    a usable F1 (the model currently loaded into the live detector),
    "failed" for runs that didn't reach F1 >= 0.5, "completed" for
    older successful runs.
    """
    id: int
    started_at: IsoUtcDatetime
    completed_at: IsoUtcDatetime | None = None
    dataset: str
    f1_score: float | None = None
    precision_score: float | None = None
    recall_score: float | None = None
    artifacts_path: str | None = None
    notes: str = ""
    status: TrainingRunStatus


class TrainingRunsResponse(BaseModel):
    """GET /api/v1/training/runs. Newest first. `active_id` is the id
    of the run currently loaded in the detector — usually the most
    recently completed successful run."""
    items: list[TrainingRun]
    active_id: int | None = None


# ---------- Upload (POST /api/v1/upload) ----------

UploadStatus = Literal["queued", "running", "completed", "failed"]


class UploadJobResponse(BaseModel):
    """Returned by POST /upload — the job is already streaming when this
    response is sent. Frontend polls GET /upload/{job_id}/status for
    progress."""
    job_id: str
    total_lines: int = Field(ge=0)
    rate: int = Field(ge=1, le=1000)
    status: UploadStatus


class UploadStatusResponse(BaseModel):
    job_id: str
    status: UploadStatus
    lines_streamed: int = Field(ge=0)
    total_lines: int = Field(ge=0)
    # Filled while running; null when the job hasn't started or has
    # finished. Estimated from the actual achieved rate so far, not the
    # configured rate, so backpressure on Redis surfaces honestly.
    eta_seconds: int | None = None
    # Truncated error string when status="failed". Null otherwise.
    error: str | None = None


# ---------- WebSocket message envelopes ----------
# These aren't auto-included in openapi.json (FastAPI doesn't introspect WS),
# but they document the WS contract so Person B has a single source of truth.

class WsAnomalyMessage(BaseModel):
    type: Literal["anomaly"]
    data: Anomaly


class WsExplanationReadyData(BaseModel):
    anomaly_id: str
    explanation_status: ExplanationStatus


class WsExplanationReadyMessage(BaseModel):
    type: Literal["explanation_ready"]
    data: WsExplanationReadyData


class WsPingMessage(BaseModel):
    type: Literal["ping"]
