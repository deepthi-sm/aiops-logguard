"""
User-driven log upload.

The frontend POSTs a `.log` / `.txt` file to `/api/v1/upload`. The file
is streamed line-by-line into the same Redis stream the live runner
consumes, tagged with `source="user-upload"` so anomalies derived from
this file are distinguishable from replayed demo data and from real
production traffic.

The endpoint returns immediately after queuing the job (synchronously
counts lines + spawns an asyncio task for the streaming). Progress is
polled via `GET /upload/{job_id}/status` — that's simpler than reusing
the websocket and it's good enough for the demo.

Limits:
  - 50 MB file cap. Rejected EARLY via the Content-Length header before
    the body is even read, so a 5 GB upload fails fast instead of
    filling the request worker's memory first.
  - Rate cap of 1000 lines/sec. Default is 50 lines/sec (matches
    `tools/log_replay`'s default). The frontend hides the rate knob;
    operators or the demo can pass `?rate=500` from the URL bar to
    accelerate ingestion during a presentation.

State storage: an in-memory dict keyed by job_id. Single-process,
single-instance — deliberately not Redis-backed because the demo only
runs one API container and survival across API restarts isn't a goal.
A real deployment would key the state in Redis or Postgres.
"""
from __future__ import annotations

import asyncio
import os
import re
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated

import redis.asyncio as redis_aio
from fastapi import APIRouter, File, HTTPException, Query, Request, UploadFile
from pydantic import BaseModel

from api.schemas import UploadJobResponse, UploadStatusResponse

# Tunables.
DEFAULT_RATE = 50
MAX_RATE = 1000
MAX_BYTES = 50 * 1024 * 1024  # 50 MB
# Origin tag applied to every anomaly derived from a user upload — used by
# the frontend's `/anomalies?origin=user-upload` filter to scope the list
# to just-uploaded data. Distinct from the per-line `source` (parsed from
# the filename) so the UI can display a meaningful host/service name.
ORIGIN_TAG = "user-upload"
LOGS_RAW_STREAM = "logs:raw"
FIELD_LINE = "line"
FIELD_SOURCE = "source"
FIELD_ORIGIN = "origin"
ALLOWED_SUFFIXES = (".log", ".txt")


def _derive_source_from_filename(filename: str) -> str:
    """Sanitise a filename into a `source` identifier for the anomaly.

    Examples:
      `BGL.log`        → `bgl`
      `Thunderbolt.log`→ `thunderbolt`
      `My Logs.txt`    → `my-logs`

    Used as the anomaly's `source` so the dashboard groups all anomalies
    from one upload coherently. The origin tag (FIELD_ORIGIN, set to
    ORIGIN_TAG) is stored separately for filtering.
    """
    stem = Path(filename).stem.lower()
    sanitised = re.sub(r"[^a-z0-9]+", "-", stem).strip("-")
    return sanitised or "user-upload"

router = APIRouter(prefix="/api/v1")


# -- in-memory job registry ------------------------------------------------


@dataclass
class _UploadJob:
    """Per-job state. `task` is the spawned asyncio.Task; we keep a ref
    so it doesn't get garbage-collected mid-flight."""
    job_id: str
    status: str  # see UploadStatus literal
    rate: int
    total_lines: int = 0
    lines_streamed: int = 0
    started_at: float | None = None
    completed_at: float | None = None
    error: str | None = None
    task: asyncio.Task | None = field(default=None, repr=False)


_jobs: dict[str, _UploadJob] = {}


def _redis_url() -> str:
    return os.environ.get("LOGGUARD_REDIS_URL", "redis://localhost:6379")


# -- background streamer ----------------------------------------------------


async def _stream_to_redis(job: _UploadJob, lines: list[str], source: str) -> None:
    """Background worker: xadd one line at a time at the configured rate.

    Each xadd produces one event for the live ingestion runner to consume.
    `source` is the parsed/derived display identifier (e.g. "bgl"); the
    origin tag (`ORIGIN_TAG = "user-upload"`) goes on a separate field so
    the dashboard can filter user-uploaded anomalies without overloading
    the displayed source.
    """
    if job.rate <= 0:
        job.status = "failed"
        job.error = "invalid rate"
        return
    inter_line_delay = 1.0 / job.rate
    redis_client: redis_aio.Redis | None = None
    try:
        redis_client = redis_aio.from_url(_redis_url(), decode_responses=True)
        await redis_client.ping()
        job.status = "running"
        job.started_at = time.monotonic()
        for line in lines:
            await redis_client.xadd(
                LOGS_RAW_STREAM,
                {FIELD_LINE: line, FIELD_SOURCE: source, FIELD_ORIGIN: ORIGIN_TAG},
            )
            job.lines_streamed += 1
            await asyncio.sleep(inter_line_delay)
        job.status = "completed"
        job.completed_at = time.monotonic()
    except asyncio.CancelledError:
        job.status = "failed"
        job.error = "cancelled"
        raise
    except Exception as e:  # noqa: BLE001
        job.status = "failed"
        # Truncate so a giant traceback doesn't get stored in process memory.
        job.error = f"{type(e).__name__}: {str(e)[:200]}"
    finally:
        if redis_client is not None:
            try:
                await redis_client.aclose()
            except Exception:  # noqa: BLE001
                pass


# -- routes ----------------------------------------------------------------


@router.post("/upload", response_model=UploadJobResponse, status_code=202)
async def upload_file(
    request: Request,
    file: Annotated[UploadFile, File(description="Log file (.log or .txt), <= 50 MB")],
    rate: Annotated[
        int,
        Query(ge=1, le=MAX_RATE, description="Lines per second to stream into Redis"),
    ] = DEFAULT_RATE,
) -> UploadJobResponse:
    # Reject early via Content-Length so a 5 GB upload doesn't get
    # buffered before we say no. Some clients omit Content-Length on
    # multipart; in that case we fall back to checking the materialised
    # body size below.
    cl_header = request.headers.get("content-length")
    if cl_header is not None:
        try:
            if int(cl_header) > MAX_BYTES:
                raise HTTPException(
                    status_code=413,
                    detail=(
                        f"File too large; max {MAX_BYTES // (1024 * 1024)} MB "
                        f"per upload."
                    ),
                )
        except ValueError:
            pass  # malformed header — let the body-size check catch it

    name = file.filename or ""
    if not name.lower().endswith(ALLOWED_SUFFIXES):
        raise HTTPException(
            status_code=400,
            detail=f"Only {', '.join(ALLOWED_SUFFIXES)} files are accepted.",
        )

    raw = await file.read()
    if len(raw) > MAX_BYTES:
        raise HTTPException(
            status_code=413,
            detail=(
                f"File too large; max {MAX_BYTES // (1024 * 1024)} MB per upload."
            ),
        )
    if not raw:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    # Decode + filter blank lines once, up front. Streamer iterates the
    # already-cleaned list so progress reporting stays accurate.
    text = raw.decode("utf-8", errors="replace")
    lines = [ln.strip() for ln in text.splitlines()]
    lines = [ln for ln in lines if ln]
    if not lines:
        raise HTTPException(
            status_code=400,
            detail="Uploaded file has no non-blank lines.",
        )

    source = _derive_source_from_filename(name)

    job_id = uuid.uuid4().hex[:12]
    job = _UploadJob(
        job_id=job_id,
        status="queued",
        rate=int(rate),
        total_lines=len(lines),
    )
    _jobs[job_id] = job
    job.task = asyncio.create_task(_stream_to_redis(job, lines, source))

    return UploadJobResponse(
        job_id=job_id,
        total_lines=job.total_lines,
        rate=job.rate,
        status=job.status,
    )


# -- /connect — server-side dataset streaming -----------------------------
#
# The Connect page lets the user paste a "datasource URL" (Redis-style,
# Datadog-style, etc) and click Save. The URL is decorative — what
# actually matters is the dataset *keyword* it contains, which we map
# to a server-side sample log file. That file is then streamed into
# Redis using the same `_stream_to_redis` path the /upload endpoint
# uses, so the dashboard fills with anomalies just like a real
# integration would.
#
# Mapping is keyword-based (case-insensitive). If no keyword matches,
# we fall back to the OpenStack abnormal sample so the demo always
# produces something interesting.
SERVER_DATASETS: dict[str, Path] = {
    "openstack": Path("training/data/openstack/openstack_abnormal.sample-500.log"),
    "abnormal":  Path("training/data/openstack/openstack_abnormal.sample-500.log"),
    "nova":      Path("training/data/openstack/openstack_abnormal.sample-500.log"),
    "datadog":   Path("training/data/openstack/openstack_abnormal.sample-500.log"),
    "apache":    Path("training/data/apache/Apache.sample-1000.log"),
    "hdfs":      Path("training/data/hdfs/HDFS.sample-200.log"),
    "splunk":    Path("training/data/openstack/openstack_normal2.sample-500.log"),
    "elastic":   Path("training/data/openstack/openstack_normal2.sample-500.log"),
}
DEFAULT_DATASET_KEY = "openstack"


def _resolve_dataset(*url_fields: str) -> tuple[str, Path]:
    """Pick a server-side dataset based on keywords in the user's URL
    fields. Returns `(dataset_key, file_path)`. Falls back to OpenStack
    abnormal so the demo always lands on something with detectable
    anomalies."""
    haystack = " ".join(s.lower() for s in url_fields if s)
    for keyword, path in SERVER_DATASETS.items():
        if keyword in haystack:
            return keyword, path
    return DEFAULT_DATASET_KEY, SERVER_DATASETS[DEFAULT_DATASET_KEY]


class ConnectRequest(BaseModel):
    redis_url: str
    log_file_path: str = ""
    webhook_url: str = ""


class ConnectResponse(BaseModel):
    job_id: str
    status: str
    dataset: str           # which sample dataset got selected
    total_lines: int
    rate: int


@router.post("/connect", response_model=ConnectResponse, status_code=202)
async def connect_datasource(body: ConnectRequest) -> ConnectResponse:
    """Trigger a server-side dataset stream from a "connection" form.

    The Connect page POSTs the user's URL fields here. We pick a
    server-side sample log based on keywords in those URLs, then
    stream that file through the same pipeline as /upload — anomalies
    appear on the dashboard tagged with the chosen dataset's source.
    """
    if not body.redis_url.strip():
        raise HTTPException(
            status_code=400,
            detail="Redis URL is required.",
        )

    dataset_key, file_path = _resolve_dataset(
        body.redis_url, body.log_file_path, body.webhook_url,
    )
    full_path = file_path
    if not full_path.is_absolute():
        # Resolve relative to backend/ so it works regardless of CWD.
        full_path = Path(__file__).resolve().parent.parent / file_path
    if not full_path.exists():
        raise HTTPException(
            status_code=500,
            detail=f"Demo dataset {dataset_key!r} not found on server at {full_path}",
        )

    text = full_path.read_text(encoding="utf-8", errors="replace")
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if not lines:
        raise HTTPException(
            status_code=500,
            detail=f"Demo dataset {dataset_key!r} is empty",
        )

    job_id = uuid.uuid4().hex[:12]
    job = _UploadJob(
        job_id=job_id,
        status="queued",
        rate=DEFAULT_RATE,
        total_lines=len(lines),
    )
    _jobs[job_id] = job
    # Source = dataset_key so the dashboard groups all "connect"-driven
    # anomalies under that label (e.g. source="openstack").
    job.task = asyncio.create_task(_stream_to_redis(job, lines, dataset_key))

    return ConnectResponse(
        job_id=job_id,
        status="queued",
        dataset=dataset_key,
        total_lines=len(lines),
        rate=DEFAULT_RATE,
    )


@router.get("/upload/{job_id}/status", response_model=UploadStatusResponse)
async def upload_status(job_id: str) -> UploadStatusResponse:
    job = _jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Upload job not found")

    eta_seconds: int | None = None
    if (
        job.status == "running"
        and job.started_at is not None
        and job.lines_streamed > 0
    ):
        elapsed = time.monotonic() - job.started_at
        if elapsed > 0:
            achieved_rate = job.lines_streamed / elapsed
            remaining = job.total_lines - job.lines_streamed
            if achieved_rate > 0 and remaining > 0:
                eta_seconds = int(remaining / achieved_rate)

    return UploadStatusResponse(
        job_id=job_id,
        status=job.status,  # type: ignore[arg-type]
        lines_streamed=job.lines_streamed,
        total_lines=job.total_lines,
        eta_seconds=eta_seconds,
        error=job.error,
    )


# Test-only helper. Lets a test reset the registry between assertions
# without yanking module-level globals via monkeypatch.
def _reset_jobs() -> None:
    _jobs.clear()
