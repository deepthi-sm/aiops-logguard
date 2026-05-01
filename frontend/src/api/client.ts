/**
 * Lightweight typed fetch wrapper around the backend's /api/v1/* surface.
 *
 * In dev, Vite's proxy routes /api → http://localhost:8000 (see vite.config.ts),
 * so we can use relative URLs and keep the code production-ready.
 */
import type {
  Anomaly,
  AnomalyListResponse,
  DriftStatus,
  Explanation,
  FeedbackRequest,
  FeedbackResponse,
  HealthResponse,
  MetricsSummary,
  Severity,
  TimelineResponse,
  TimelineWindow,
} from "./types";

const BASE = "/api/v1";

class ApiError extends Error {
  constructor(
    public status: number,
    public detail: string,
  ) {
    super(`API ${status}: ${detail}`);
    this.name = "ApiError";
  }
}

async function request<T>(
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
  // 202 with empty body is part of the contract for /explanation when pending.
  if (res.status === 202) {
    return { status: 202, data: null };
  }
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = (await res.json()) as { detail?: string };
      if (body.detail) detail = body.detail;
    } catch {
      /* response wasn't JSON; keep statusText */
    }
    throw new ApiError(res.status, detail);
  }
  const data = (await res.json()) as T;
  return { status: res.status, data };
}

// -- Anomalies ------------------------------------------------------------

export interface ListAnomaliesParams {
  limit?: number;
  since?: string;
  severity?: Severity;
  cursor?: string;
}

export async function listAnomalies(
  params: ListAnomaliesParams = {},
): Promise<AnomalyListResponse> {
  const search = new URLSearchParams();
  if (params.limit) search.set("limit", String(params.limit));
  if (params.since) search.set("since", params.since);
  if (params.severity) search.set("severity", params.severity);
  if (params.cursor) search.set("cursor", params.cursor);
  const qs = search.toString();
  const { data } = await request<AnomalyListResponse>(
    `/anomalies${qs ? `?${qs}` : ""}`,
  );
  return data!;
}

export async function getAnomaly(id: string): Promise<Anomaly> {
  const { data } = await request<Anomaly>(`/anomalies/${encodeURIComponent(id)}`);
  return data!;
}

/**
 * Returns the explanation OR null when the backend signals 202 (pending).
 * Frontend renders a spinner until the WebSocket pushes "explanation_ready"
 * for this anomaly.
 */
export async function getExplanation(id: string): Promise<Explanation | null> {
  const { status, data } = await request<Explanation>(
    `/anomalies/${encodeURIComponent(id)}/explanation`,
  );
  if (status === 202) return null;
  return data!;
}

export async function postFeedback(
  id: string,
  body: FeedbackRequest,
): Promise<FeedbackResponse> {
  const { data } = await request<FeedbackResponse>(
    `/anomalies/${encodeURIComponent(id)}/feedback`,
    {
      method: "POST",
      body: JSON.stringify(body),
    },
  );
  return data!;
}

// -- Metrics --------------------------------------------------------------

export async function getMetricsSummary(): Promise<MetricsSummary> {
  const { data } = await request<MetricsSummary>(`/metrics/summary`);
  return data!;
}

export async function getTimeline(
  window: TimelineWindow,
): Promise<TimelineResponse> {
  const { data } = await request<TimelineResponse>(
    `/metrics/timeline?window=${window}`,
  );
  return data!;
}

// -- System ---------------------------------------------------------------

export async function getDrift(): Promise<DriftStatus> {
  const { data } = await request<DriftStatus>(`/system/drift`);
  return data!;
}

export async function getHealth(): Promise<HealthResponse> {
  const { data } = await request<HealthResponse>(`/health`);
  return data!;
}

export { ApiError };
