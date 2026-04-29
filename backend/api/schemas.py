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


# ---------- Feedback ----------

class FeedbackRequest(BaseModel):
    feedback: Feedback


class FeedbackResponse(BaseModel):
    ok: bool


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
