"""
Stub REST endpoints for the integration contract (docs/architecture/api_contract.md).

Step 2 of CLAUDE.md "Build order": every endpoint returns hardcoded fixtures
shaped exactly like real responses, so /openapi.json is publishable and Person
B can codegen her TypeScript client. DB / Redis wiring lands in Step 4.

The fixtures are imported from api.mock_data so the same data backs every
endpoint and the tests can assert against known values.
"""
import base64
import binascii
import json
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Response, status

from api import mock_data
from api.schemas import (
    Anomaly,
    AnomalyListResponse,
    DriftStatus,
    Explanation,
    FeedbackRequest,
    FeedbackResponse,
    MetricsSummary,
    Severity,
    TimelineResponse,
    TimelineWindow,
)

router = APIRouter(prefix="/api/v1")


# ---------- pagination cursor (opaque to frontend) ----------

def _encode_cursor(offset: int) -> str:
    payload = json.dumps({"offset": offset}).encode()
    return base64.urlsafe_b64encode(payload).decode()


def _decode_cursor(cursor: str | None) -> int:
    if not cursor:
        return 0
    try:
        decoded = base64.urlsafe_b64decode(cursor.encode())
        payload = json.loads(decoded)
        offset = int(payload["offset"])
        if offset < 0:
            raise ValueError("negative offset")
        return offset
    except (binascii.Error, json.JSONDecodeError, KeyError, TypeError, ValueError) as e:
        raise HTTPException(status_code=400, detail="Invalid cursor") from e


# ---------- /anomalies ----------

@router.get("/anomalies", response_model=AnomalyListResponse)
async def list_anomalies(
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    since: Annotated[datetime | None, Query()] = None,
    severity: Annotated[Severity | None, Query()] = None,
    cursor: Annotated[str | None, Query()] = None,
) -> AnomalyListResponse:
    items = mock_data.all_anomalies()

    if severity is not None:
        items = [a for a in items if a.severity == severity]

    if since is not None:
        # Normalise to UTC so naive timestamps don't compare against aware ones.
        since_aware = since if since.tzinfo else since.replace(tzinfo=UTC)
        items = [a for a in items if a.detected_at > since_aware]

    offset = _decode_cursor(cursor)
    page = items[offset : offset + limit]
    next_offset = offset + len(page)
    next_cursor = _encode_cursor(next_offset) if next_offset < len(items) else None
    return AnomalyListResponse(items=page, next_cursor=next_cursor)


@router.get("/anomalies/{anomaly_id}", response_model=Anomaly)
async def get_anomaly(anomaly_id: str) -> Anomaly:
    a = mock_data.find_anomaly(anomaly_id)
    if a is None:
        raise HTTPException(status_code=404, detail="Anomaly not found")
    return a


@router.get(
    "/anomalies/{anomaly_id}/explanation",
    response_model=Explanation,
    responses={
        202: {"description": "Explanation pending — poll or wait for websocket update"},
        404: {"description": "Anomaly not found"},
    },
)
async def get_explanation(anomaly_id: str) -> Explanation | Response:
    a = mock_data.find_anomaly(anomaly_id)
    if a is None:
        raise HTTPException(status_code=404, detail="Anomaly not found")
    if a.explanation_status == "pending":
        # Per contract: 202 with empty body. Frontend polls or waits for ws.
        return Response(status_code=status.HTTP_202_ACCEPTED)
    explanation = mock_data.explanation_for(anomaly_id)
    if explanation is None:
        # explanation_status is "failed" — no detail available. Surface as 500
        # for now; a richer error payload lands when the RAG worker arrives.
        raise HTTPException(status_code=500, detail="Explanation generation failed")
    return explanation


@router.post("/anomalies/{anomaly_id}/feedback", response_model=FeedbackResponse)
async def post_feedback(anomaly_id: str, body: FeedbackRequest) -> FeedbackResponse:
    if mock_data.find_anomaly(anomaly_id) is None:
        raise HTTPException(status_code=404, detail="Anomaly not found")
    # Stub: accept and ack. Real impl writes to anomalies.feedback in PR 4.
    _ = body  # intentionally unused — schema validation is the contract guard
    return FeedbackResponse(ok=True)


# ---------- /metrics ----------

@router.get("/metrics/summary", response_model=MetricsSummary)
async def metrics_summary() -> MetricsSummary:
    return mock_data.metrics_summary()


@router.get("/metrics/timeline", response_model=TimelineResponse)
async def metrics_timeline(
    window: Annotated[TimelineWindow, Query()],
) -> TimelineResponse:
    return mock_data.timeline(window)


# ---------- /system ----------

@router.get("/system/drift", response_model=DriftStatus)
async def system_drift() -> DriftStatus:
    return mock_data.drift_status()
