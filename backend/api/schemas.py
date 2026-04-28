"""
Pydantic models — the integration contract with the frontend.

FastAPI generates openapi.json from these models. Person B's TypeScript
client is generated from that file. Changing a field here without bumping
the API version is a silent breaking change. See docs/architecture/api_contract.md.

PR 1 ships only HealthResponse. The full contract (Anomaly, MetricsSummary,
TimelineResponse, DriftStatus, FeedbackRequest, etc.) lands in PR 2.
"""
from typing import Literal

from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    version: str
    uptime_s: int
