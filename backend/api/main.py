"""
FastAPI application entrypoint.

PR 2 wires up the full stub REST + WebSocket contract so /openapi.json can be
consumed for client codegen by Person B. CORS is permissive for the Vite dev
server at http://localhost:5173. Real DB / Redis / RAG hookup arrives in
later PRs (see CLAUDE.md "Build order").
"""
import os
import time

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routes import router as rest_router
from api.schemas import HealthResponse
from api.ws import router as ws_router

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

app.include_router(rest_router)
app.include_router(ws_router)


@app.get("/api/v1/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(
        status="ok",
        version=VERSION,
        uptime_s=int(time.monotonic() - _started_at),
    )
