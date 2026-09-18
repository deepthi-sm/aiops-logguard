/**
 * API client. Routes calls to either the mock layer (for dev / when the
 * backend isn't ready) or real fetch against the FastAPI backend.
 *
 * Toggle:
 *   VITE_USE_MOCK=true  → use MOCK_* fixtures (default during dev)
 *   VITE_USE_MOCK=false → real /api/v1 calls (Vite proxies to :8000)
 *
 * Anything mock-only goes through `mock.ts`. Anything real-only goes
 * through `fetchJson()`. Both paths return the same types so callers
 * (queries.ts, components) don't branch.
 */
import type {
  Anomaly,
  AnomalyListResponse,
  DriftStatus,
  Explanation,
  FeedbackHistoryResponse,
  FeedbackRequest,
  FeedbackResponse,
  HealthResponse,
  MetricsSummary,
  Origin,
  Severity,
  TimelineResponse,
  TimelineWindow,
  SystemQueueResponse,
  SystemServicesResponse,
  TrainingRunsResponse,
  UploadJobResponse,
  UploadStatusResponse,
} from "../types";
import {
  findMockAnomaly,
  findMockExplanation,
  MOCK_ANOMALIES,
  MOCK_DRIFT,
  MOCK_METRICS_SUMMARY,
  mockTimeline,
} from "./mock";

// Default false — the live backend is the source of truth for the demo.
// Set VITE_USE_MOCK=true in `.env.local` to force fixtures (handy when
// the backend is offline for frontend-only work).
const USE_MOCK = import.meta.env.VITE_USE_MOCK === "true";

const BASE = "/api/v1";

// -- error type -----------------------------------------------------------

export class ApiError extends Error {
  constructor(
    public status: number,
    public detail: string,
  ) {
    super(`API ${status}: ${detail}`);
    this.name = "ApiError";
  }
}

// -- low-level helpers ----------------------------------------------------

async function fetchJson<T>(
  path: string,
  init: RequestInit = {},
): Promise<{ status: number; data: T | null }> {
  const res = await fetch(`${BASE}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init.headers ?? {}),
    },
  });
  // 202 = "explanation pending, body intentionally empty" per the contract.
  if (res.status === 202) return { status: 202, data: null };
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = (await res.json()) as { detail?: string };
      if (body.detail) detail = body.detail;
    } catch {
      /* not JSON */
    }
    throw new ApiError(res.status, detail);
  }
  return { status: res.status, data: (await res.json()) as T };
}

/** Tiny helper so mock paths feel like real network calls — gives the UI
 * a chance to render skeletons. ~120 ms is below noticeable while still
 * exercising loading states. */
function mockDelay<T>(value: T, ms = 120): Promise<T> {
  return new Promise((resolve) => setTimeout(() => resolve(value), ms));
}

// -- anomalies ------------------------------------------------------------

export interface ListAnomaliesParams {
  limit?: number;
  since?: string;
  severity?: Severity;
  source?: string;
  origin?: Origin;
  cursor?: string;
}

export async function listAnomalies(
  params: ListAnomaliesParams = {},
): Promise<AnomalyListResponse> {
  if (USE_MOCK) {
    let items = [...MOCK_ANOMALIES];
    if (params.severity) {
      items = items.filter((a) => a.severity === params.severity);
    }
    if (params.since) {
      items = items.filter((a) => a.detected_at > params.since!);
    }
    if (params.source) {
      items = items.filter((a) => a.source === params.source);
    }
    if (params.origin) {
      items = items.filter((a) => a.origin === params.origin);
    }
    if (params.limit !== undefined) {
      items = items.slice(0, params.limit);
    }
    return mockDelay({ items, next_cursor: null });
  }
  const search = new URLSearchParams();
  if (params.limit) search.set("limit", String(params.limit));
  if (params.since) search.set("since", params.since);
  if (params.severity) search.set("severity", params.severity);
  if (params.source) search.set("source", params.source);
  if (params.origin) search.set("origin", params.origin);
  if (params.cursor) search.set("cursor", params.cursor);
  const qs = search.toString();
  const { data } = await fetchJson<AnomalyListResponse>(
    `/anomalies${qs ? `?${qs}` : ""}`,
  );
  return data!;
}

export async function getAnomaly(id: string): Promise<Anomaly> {
  if (USE_MOCK) {
    const a = findMockAnomaly(id);
    if (!a) throw new ApiError(404, "Anomaly not found");
    return mockDelay(a);
  }
  const { data } = await fetchJson<Anomaly>(
    `/anomalies/${encodeURIComponent(id)}`,
  );
  return data!;
}

/**
 * Returns the explanation OR null when the backend signals 202 (pending).
 * The frontend renders a "generating" placeholder until the WS pushes
 * "explanation_ready" or the polled refetch returns a real body.
 */
export async function getExplanation(id: string): Promise<Explanation | null> {
  if (USE_MOCK) {
    const a = findMockAnomaly(id);
    if (!a) throw new ApiError(404, "Anomaly not found");
    if (a.explanation_status === "pending") return mockDelay(null);
    if (a.explanation_status === "failed") {
      throw new ApiError(500, "Explanation generation failed");
    }
    const exp = findMockExplanation(id);
    return mockDelay(exp ?? null);
  }
  const { status, data } = await fetchJson<Explanation>(
    `/anomalies/${encodeURIComponent(id)}/explanation`,
  );
  if (status === 202) return null;
  return data!;
}

export async function postFeedback(
  id: string,
  body: FeedbackRequest,
): Promise<FeedbackResponse> {
  if (USE_MOCK) {
    if (!findMockAnomaly(id)) throw new ApiError(404, "Anomaly not found");
    return mockDelay({ ok: true }, 200);
  }
  const { data } = await fetchJson<FeedbackResponse>(
    `/anomalies/${encodeURIComponent(id)}/feedback`,
    { method: "POST", body: JSON.stringify(body) },
  );
  return data!;
}

export async function listFeedback(
  limit = 100,
): Promise<FeedbackHistoryResponse> {
  if (USE_MOCK) {
    // No mock fixture exists for the history view — return an empty
    // shape so the UI shows its empty-state instead of crashing.
    return mockDelay({
      items: [],
      total: 0,
      true_positive: 0,
      false_positive: 0,
    });
  }
  const { data } = await fetchJson<FeedbackHistoryResponse>(
    `/feedback?limit=${encodeURIComponent(limit)}`,
  );
  return data!;
}

// -- metrics --------------------------------------------------------------

export async function getMetricsSummary(): Promise<MetricsSummary> {
  if (USE_MOCK) return mockDelay(MOCK_METRICS_SUMMARY);
  const { data } = await fetchJson<MetricsSummary>(`/metrics/summary`);
  return data!;
}

export async function getTimeline(
  window: TimelineWindow,
): Promise<TimelineResponse> {
  if (USE_MOCK) return mockDelay(mockTimeline(window));
  const { data } = await fetchJson<TimelineResponse>(
    `/metrics/timeline?window=${window}`,
  );
  return data!;
}

// -- system ---------------------------------------------------------------

export async function listTrainingRuns(
  limit = 50,
): Promise<TrainingRunsResponse> {
  if (USE_MOCK) {
    // No mock fixture — return an empty list; the page renders its
    // empty-state instead.
    return mockDelay({ items: [], active_id: null });
  }
  const { data } = await fetchJson<TrainingRunsResponse>(
    `/training/runs?limit=${encodeURIComponent(limit)}`,
  );
  return data!;
}


export async function getSystemServices(): Promise<SystemServicesResponse> {
  if (USE_MOCK) return mockDelay({ items: [] });
  const { data } = await fetchJson<SystemServicesResponse>(`/system/services`);
  return data!;
}


export async function getSystemQueue(): Promise<SystemQueueResponse> {
  if (USE_MOCK) {
    return mockDelay({
      pending: 0,
      ready: 0,
      failed: 0,
      oldest_pending_id: null,
      oldest_pending_at: null,
    });
  }
  const { data } = await fetchJson<SystemQueueResponse>(`/system/queue`);
  return data!;
}


export async function getDrift(): Promise<DriftStatus> {
  if (USE_MOCK) return mockDelay(MOCK_DRIFT);
  const { data } = await fetchJson<DriftStatus>(`/system/drift`);
  return data!;
}

export async function getHealth(): Promise<HealthResponse> {
  if (USE_MOCK) {
    return mockDelay({
      status: "ok",
      version: "0.1.0-mock",
      uptime_s: Math.floor(performance.now() / 1000),
    });
  }
  const { data } = await fetchJson<HealthResponse>(`/health`);
  return data!;
}

export const isMockMode = USE_MOCK;

/**
 * DELETE /api/v1/anomalies — wipes ALL anomalies + drift events.
 * Returns the count of rows deleted. Used between demo uploads so each
 * upload starts from a clean dashboard.
 */
export async function clearAllAnomalies(): Promise<{ deleted: number }> {
  if (USE_MOCK) {
    return mockDelay({ deleted: 0 });
  }
  const res = await fetch(`${BASE}/anomalies`, { method: "DELETE" });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = (await res.json()) as { detail?: string };
      if (body.detail) detail = body.detail;
    } catch {
      /* not JSON */
    }
    throw new ApiError(res.status, detail);
  }
  return (await res.json()) as { deleted: number };
}

// -- upload ---------------------------------------------------------------

/** Backend constant kept in sync with `MAX_BYTES` in `api/upload.py`. */
export const UPLOAD_MAX_BYTES = 50 * 1024 * 1024;

/**
 * POST /api/v1/upload — multipart, returns 202 with a job id. Caller
 * then polls `getUploadStatus(jobId)` for progress.
 *
 * The optional `rate` (lines/sec) is passed as a query param when
 * provided — the backend caps it at 1000. Default omits the param so
 * the backend uses its own default (50).
 */
export async function uploadLogFile(
  file: File,
  options: { rate?: number } = {},
): Promise<UploadJobResponse> {
  if (USE_MOCK) {
    // Mock mode just fakes a completed job — there's no real Redis to
    // stream into. Useful for frontend-only iteration.
    return mockDelay(
      {
        job_id: "mock_" + Math.random().toString(36).slice(2, 10),
        total_lines: 0,
        rate: options.rate ?? 50,
        status: "completed" as const,
      },
      300,
    );
  }
  const form = new FormData();
  form.append("file", file);
  const qs = options.rate ? `?rate=${encodeURIComponent(options.rate)}` : "";
  // We can't use `fetchJson()` here because it always sets
  // Content-Type: application/json. Multipart needs the browser to set
  // its own multipart Content-Type with the boundary.
  const res = await fetch(`${BASE}/upload${qs}`, {
    method: "POST",
    body: form,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = (await res.json()) as { detail?: string };
      if (body.detail) detail = body.detail;
    } catch {
      /* not JSON */
    }
    throw new ApiError(res.status, detail);
  }
  return (await res.json()) as UploadJobResponse;
}

export async function getUploadStatus(jobId: string): Promise<UploadStatusResponse> {
  if (USE_MOCK) {
    return mockDelay({
      job_id: jobId,
      status: "completed" as const,
      lines_streamed: 0,
      total_lines: 0,
      eta_seconds: null,
      error: null,
    });
  }
  const { data } = await fetchJson<UploadStatusResponse>(
    `/upload/${encodeURIComponent(jobId)}/status`,
  );
  return data!;
}
