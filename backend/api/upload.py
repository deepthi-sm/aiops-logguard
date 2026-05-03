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
import json
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
MIN_RATE = 10
MAX_RATE = 100
MAX_BYTES = 50 * 1024 * 1024  # 50 MB
# Hard cap on lines per upload / per /connect fetch. Raised from the
# implicit ~2k limit (file sizes typical demo users tested with) to
# 20k after a teacher-feedback round on Phase 1 Review 3 — the model
# itself has no problem with larger inputs; this was a guardrail.
MAX_LINES = 20_000
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


async def _stream_to_redis(
    job: _UploadJob, lines: list[tuple[str, str]],
) -> None:
    """Background worker: xadd one event at a time at the configured rate.

    `lines` is a list of `(raw_text, source)` tuples. For uploads the
    source is uniform (filename-derived) across every tuple. For
    `/connect` with a real URL fetch, each tuple may carry a different
    source extracted from the JSONL response — that's how a single
    Connect Save produces a multi-source mix on the dashboard.

    The origin tag (`ORIGIN_TAG = "user-upload"`) is uniform: both flows
    are user-driven, both go through this code path. Source is the
    display identifier; origin is the filter tag.
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
        for raw, source in lines:
            await redis_client.xadd(
                LOGS_RAW_STREAM,
                {FIELD_LINE: raw, FIELD_SOURCE: source, FIELD_ORIGIN: ORIGIN_TAG},
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
        Query(
            ge=MIN_RATE, le=MAX_RATE,
            description=(
                f"Lines per second to stream into Redis. "
                f"Range {MIN_RATE}-{MAX_RATE}, default {DEFAULT_RATE}."
            ),
        ),
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
    if len(lines) > MAX_LINES:
        raise HTTPException(
            status_code=413,
            detail=(
                f"File has {len(lines):,} non-blank lines; max {MAX_LINES:,} "
                "per upload. Split the file or lower the line count."
            ),
        )

    source = _derive_source_from_filename(name)
    typed_lines: list[tuple[str, str]] = [(ln, source) for ln in lines]

    job_id = uuid.uuid4().hex[:12]
    job = _UploadJob(
        job_id=job_id,
        status="queued",
        rate=int(rate),
        total_lines=len(lines),
    )
    _jobs[job_id] = job
    job.task = asyncio.create_task(_stream_to_redis(job, typed_lines))

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
    # Optional rate override; same range/default as /upload.
    rate: int | None = None


class ConnectResponse(BaseModel):
    job_id: str
    status: str
    dataset: str           # one of: "<keyword>" | "url-fetch"
    total_lines: int
    rate: int


def _is_http_url(value: str) -> bool:
    """Tighter than just `startswith("http")` — guards against accidental
    paste of an `https-flavoured` username or similar."""
    s = value.strip().lower()
    return s.startswith("http://") or s.startswith("https://")


async def _fetch_jsonl_lines(url: str) -> list[tuple[str, str]] | None:
    """HTTP-fetch a URL expecting NDJSON (`application/x-ndjson`) and
    return parsed `(line, source)` tuples. Returns `None` if the fetch
    fails for any reason (timeout, non-200, malformed body) — caller
    falls back to the keyword-matched sample file path."""
    import httpx
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            body = resp.text
    except Exception:  # noqa: BLE001 — fetch failures must NOT 500 the route
        return None

    out: list[tuple[str, str]] = []
    for raw_line in body.splitlines():
        s = raw_line.strip()
        if not s:
            continue
        try:
            obj = json.loads(s)
        except json.JSONDecodeError:
            return None  # not NDJSON; fall back
        line = obj.get("line")
        source = obj.get("source")
        if not isinstance(line, str) or not isinstance(source, str):
            return None
        out.append((line, source))
        if len(out) >= MAX_LINES:
            break
    return out if out else None


@router.post("/connect", response_model=ConnectResponse, status_code=202)
async def connect_datasource(body: ConnectRequest) -> ConnectResponse:
    """Trigger a streaming "connection" from a user-supplied URL.

    Two paths:
      1. **Real HTTP fetch.** If `redis_url` looks like an HTTP(S) URL
         we fetch it expecting NDJSON `{source, line}` events and
         stream each into Redis with its own source. This is the
         demo-grade path — paste `http://localhost:8000/api/v1/demo/stream`
         and the synthesized BGL/Thunderbird/HDFS mix flows in.
      2. **Keyword-matched sample file fallback.** If the URL isn't
         HTTP-reachable or the response isn't NDJSON, we resolve the
         URL keyword to a server-side sample log (the previous
         behaviour) so the demo never dead-locks on a typo.

    Both paths converge on the same `_stream_to_redis` worker so
    downstream — ingestion, scoring, dashboard — is identical to the
    upload flow.
    """
    if not body.redis_url.strip():
        raise HTTPException(
            status_code=400,
            detail="Redis URL is required.",
        )

    rate = int(body.rate) if body.rate is not None else DEFAULT_RATE
    if not (MIN_RATE <= rate <= MAX_RATE):
        raise HTTPException(
            status_code=400,
            detail=f"rate must be {MIN_RATE}-{MAX_RATE} lines/sec.",
        )

    dataset_label = "url-fetch"
    typed_lines: list[tuple[str, str]] | None = None

    # Path 1: real HTTP fetch
    if _is_http_url(body.redis_url):
        typed_lines = await _fetch_jsonl_lines(body.redis_url)
        if typed_lines is not None:
            dataset_label = "url-fetch"

    # Path 2: keyword fallback (no HTTP fetch attempted, OR the fetch
    # didn't yield usable NDJSON)
    if typed_lines is None:
        dataset_key, file_path = _resolve_dataset(
            body.redis_url, body.log_file_path, body.webhook_url,
        )
        full_path = file_path
        if not full_path.is_absolute():
            full_path = Path(__file__).resolve().parent.parent / file_path
        if not full_path.exists():
            raise HTTPException(
                status_code=500,
                detail=(
                    f"Demo dataset {dataset_key!r} not found on server "
                    f"at {full_path}"
                ),
            )
        text = full_path.read_text(encoding="utf-8", errors="replace")
        raw_lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        if not raw_lines:
            raise HTTPException(
                status_code=500,
                detail=f"Demo dataset {dataset_key!r} is empty",
            )
        if len(raw_lines) > MAX_LINES:
            raw_lines = raw_lines[:MAX_LINES]
        typed_lines = [(ln, dataset_key) for ln in raw_lines]
        dataset_label = dataset_key

    job_id = uuid.uuid4().hex[:12]
    job = _UploadJob(
        job_id=job_id,
        status="queued",
        rate=rate,
        total_lines=len(typed_lines),
    )
    _jobs[job_id] = job
    job.task = asyncio.create_task(_stream_to_redis(job, typed_lines))

    return ConnectResponse(
        job_id=job_id,
        status="queued",
        dataset=dataset_label,
        total_lines=len(typed_lines),
        rate=rate,
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
