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
  FeedbackRequest,
  FeedbackResponse,
  HealthResponse,
  MetricsSummary,
  Severity,
  TimelineResponse,
  TimelineWindow,
} from "../types";
import {
  findMockAnomaly,
  findMockExplanation,
  MOCK_ANOMALIES,
  MOCK_DRIFT,
  MOCK_METRICS_SUMMARY,
  mockTimeline,
} from "./mock";

// Default true — pages get to render against fixtures from the moment they
// land. Step 11 of the spec's build order flips this to false.
const USE_MOCK = import.meta.env.VITE_USE_MOCK !== "false";

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
    if (params.limit !== undefined) {
      items = items.slice(0, params.limit);
    }
    return mockDelay({ items, next_cursor: null });
  }
  const search = new URLSearchParams();
  if (params.limit) search.set("limit", String(params.limit));
  if (params.since) search.set("since", params.since);
  if (params.severity) search.set("severity", params.severity);
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
