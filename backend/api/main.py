"""
FastAPI application entrypoint.

PR 1 wires up only /api/v1/health. Routes, websocket, and DB pool arrive in
later PRs (see CLAUDE.md "Build order"). CORS is permissive for the Vite dev
server at http://localhost:5173 — Person B's frontend will call against this.
"""
import os
import time

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.schemas import HealthResponse

VERSION = os.environ.get("LOGGUARD_VERSION", "0.1.0")
_started_at = time.monotonic()

app = FastAPI(
    title="AIOps-LogGuard API",
    version=VERSION,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/v1/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(
        status="ok",
        version=VERSION,
        uptime_s=int(time.monotonic() - _started_at),
    )
