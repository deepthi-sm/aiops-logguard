# API Contract Reference

This document is the full reference for the REST + WebSocket API. The Pydantic models in `backend/api/schemas.py` are the source of truth — this doc explains them.

**Base URL:** `http://localhost:8000` in dev. Production URL is environment-specific.
**API version:** `v1`. Bump to `v2` only on breaking changes.
**Auth:** none in dev. Production should use API keys (Bearer token in `Authorization` header).
**CORS:** allow `http://localhost:5173` (Vite dev server) and the production frontend origin.

## Pydantic schemas (the source of truth)

```python
# backend/api/schemas.py
from pydantic import BaseModel
from typing import Literal, Optional
from datetime import datetime

Severity = Literal["critical", "warning", "info"]
ExplanationStatus = Literal["pending", "ready", "failed"]
Feedback = Literal["true_positive", "false_positive"]

class ContributingLine(BaseModel):
    line: str
    attention: float  # 0..1

class Anomaly(BaseModel):
    id: str
    detected_at: datetime
    severity: Severity
    source: str
    ensemble_score: float
    confidence: float
    failure_probability: float
    predicted_failure_window_min: Optional[int]
    log_template: str
    sequence_preview: list[str]
    top_contributing_lines: list[ContributingLine]
    explanation_status: ExplanationStatus
    cluster_id: str
    cluster_size: int

class AnomalyListResponse(BaseModel):
    items: list[Anomaly]
    next_cursor: Optional[str]

class SimilarIncident(BaseModel):
    incident_id: str
    template: str
    resolved_at: Optional[datetime]
    similarity_score: float

class Explanation(BaseModel):
    root_cause: str
    recommended_fix: str
    similar_incidents: list[SimilarIncident]
    attention_weights: list[float]

class MetricsSummary(BaseModel):
    total_24h: int
    critical_24h: int
    warning_24h: int
    info_24h: int
    avg_confidence: float
    drift_score: float
    last_retrain: Optional[datetime]

class TimelineBucket(BaseModel):
    ts: datetime
    critical: int
    warning: int
    info: int

class TimelineResponse(BaseModel):
    window: Literal["1h", "24h", "7d"]
    buckets: list[TimelineBucket]

class DriftStatus(BaseModel):
    drift_score: float
    last_retrain: Optional[datetime]
    status: Literal["healthy", "drift_high", "drift_critical"]
    psi_score: float

class FeedbackRequest(BaseModel):
    feedback: Feedback

class FeedbackResponse(BaseModel):
    ok: bool

class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    version: str
    uptime_s: int
```

## Endpoints

### `GET /api/v1/health`

Liveness check. Used by load balancer, Docker healthcheck, and the frontend connection pill.

**Response 200:** `HealthResponse`

```json
{
  "status": "ok",
  "version": "0.1.0",
  "uptime_s": 12453
}
```

`status` is `"degraded"` if any dependency (Redis, Postgres, Ollama) is down but the API is still responding. `"ok"` only when everything is healthy.

---

### `GET /api/v1/anomalies`

Paginated anomaly list, newest first.

**Query params:**
- `limit` (int, default 50, max 200) — page size
- `since` (ISO 8601, optional) — only anomalies after this timestamp
- `severity` (string, optional) — filter by `critical` | `warning` | `info`
- `cursor` (string, optional) — opaque cursor for pagination

**Response 200:** `AnomalyListResponse`

```json
{
  "items": [/* Anomaly objects */],
  "next_cursor": "eyJkZXRlY3RlZF9hdCI6IjIwMjYtMDQtMjhUMTA6MTQ6MjJaIn0="
}
```

Pagination: pass `next_cursor` from previous response as `cursor` param to get next page. `next_cursor` is `null` on the last page.

---

### `GET /api/v1/anomalies/{id}`

Single anomaly detail.

**Path param:** `id` — anomaly ID like `anom_2026-04-28T10:14:22_a1b2`

**Response 200:** `Anomaly`
**Response 404:** `{ "detail": "Anomaly not found" }`

---

### `GET /api/v1/anomalies/{id}/explanation`

RAG + LLaMA root cause explanation.

**Response 200:** `Explanation`

```json
{
  "root_cause": "High reconstruction error in NameNode connection logs. Pattern matches connection pool exhaustion seen in incident #247.",
  "recommended_fix": "1. Check NameNode connection pool config\n2. Review recent traffic spike\n3. Restart NameNode service if pool is saturated",
  "similar_incidents": [
    {
      "incident_id": "inc_247",
      "template": "ERROR blk_* NameNode connection refused from *",
      "resolved_at": "2024-01-15T14:32:11Z",
      "similarity_score": 0.91
    }
  ],
  "attention_weights": [0.31, 0.28, 0.15, 0.09, 0.07, 0.05, 0.05]
}
```

**Response 202:** if `explanation_status` is `pending`, return 202 with empty body. Frontend should poll or wait for websocket update.
**Response 404:** anomaly doesn't exist.

---

### `GET /api/v1/metrics/summary`

Top-line KPIs for the dashboard cards.

**Response 200:** `MetricsSummary`

```json
{
  "total_24h": 142,
  "critical_24h": 3,
  "warning_24h": 28,
  "info_24h": 111,
  "avg_confidence": 0.84,
  "drift_score": 0.12,
  "last_retrain": "2026-04-25T03:00:00Z"
}
```

---

### `GET /api/v1/metrics/timeline`

Anomaly counts bucketed for the timeline chart.

**Query params:**
- `window` (required) — `1h` | `24h` | `7d`

Bucket sizes:
- `1h` → 60 buckets of 1 minute each
- `24h` → 96 buckets of 15 minutes each
- `7d` → 168 buckets of 1 hour each

**Response 200:** `TimelineResponse`

```json
{
  "window": "24h",
  "buckets": [
    { "ts": "2026-04-28T00:00:00Z", "critical": 0, "warning": 2, "info": 5 },
    { "ts": "2026-04-28T00:15:00Z", "critical": 1, "warning": 0, "info": 3 }
  ]
}
```

---

### `GET /api/v1/system/drift`

Current model drift status.

**Response 200:** `DriftStatus`

```json
{
  "drift_score": 0.12,
  "last_retrain": "2026-04-25T03:00:00Z",
  "status": "healthy",
  "psi_score": 0.08
}
```

`status`:
- `healthy` — PSI < 0.25
- `drift_high` — PSI 0.25–0.4 (logged)
- `drift_critical` — PSI > 0.4 (retrain triggered)

---

### `POST /api/v1/anomalies/{id}/feedback`

Engineer marks an anomaly as true or false positive. Used for human-in-the-loop labelling for next retrain.

**Body:** `FeedbackRequest`

```json
{ "feedback": "true_positive" }
```

**Response 200:** `FeedbackResponse`

```json
{ "ok": true }
```

**Response 404:** anomaly doesn't exist.

---

### `WS /api/v1/ws/anomalies`

WebSocket. Server pushes a canonical `Anomaly` JSON object every time a new anomaly is detected.

**Connection:**
```
ws://localhost:8000/api/v1/ws/anomalies
```

**Server messages:**
```json
{
  "type": "anomaly",
  "data": { /* Anomaly object */ }
}
```

```json
{
  "type": "explanation_ready",
  "data": { "anomaly_id": "anom_...", "explanation_status": "ready" }
}
```

**Client messages:** ignored. The websocket is server-push only. Clients reconnect on disconnect with exponential backoff.

**Heartbeat:** server sends `{ "type": "ping" }` every 30 seconds. Client may respond with `{ "type": "pong" }` or ignore.

## Error responses

All errors follow:
```json
{
  "detail": "Human-readable error message",
  "error_code": "OPTIONAL_MACHINE_READABLE_CODE"
}
```

Common status codes:
- `400` — bad request (validation failed)
- `404` — resource not found
- `422` — unprocessable entity (Pydantic validation error, includes field details)
- `500` — server error
- `503` — service unavailable (a dependency is down)

## Versioning rule

**Breaking changes require a version bump (`v1` → `v2`).** Breaking includes:
- Removing a field from an Anomaly
- Renaming a field
- Changing a field's type
- Removing an endpoint
- Changing an endpoint's path

Non-breaking (allowed in `v1`):
- Adding a new optional field
- Adding a new endpoint
- Adding a new enum value (cautiously — frontends may not handle it)

When bumping, run both versions in parallel for at least one sprint to give the frontend time to migrate.
