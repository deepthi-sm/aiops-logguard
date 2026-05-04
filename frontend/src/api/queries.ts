/**
 * TanStack Query hooks — cache + auto-refresh + loading state in one place.
 *
 * Polling cadences are tuned per endpoint:
 *   - anomaly list:   5 s  (also patched live by the WS in Step 9)
 *   - metrics summary 10 s
 *   - timeline        30 s
 *   - drift           60 s
 *
 * The explanation hook polls every 2 s ONLY while `status === 'pending'`,
 * matching the spec.
 */
import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseQueryOptions,
} from "@tanstack/react-query";
import {
  clearAllAnomalies,
  getAnomaly,
  getDrift,
  getExplanation,
  getHealth,
  getMetricsSummary,
  getTimeline,
  getUploadStatus,
  listAnomalies,
  listFeedback,
  postFeedback,
  uploadLogFile,
  type ListAnomaliesParams,
} from "./client";
import type {
  Anomaly,
  AnomalyListResponse,
  DriftStatus,
  Explanation,
  ExplanationStatus,
  FeedbackHistoryResponse,
  FeedbackRequest,
  FeedbackResponse,
  HealthResponse,
  MetricsSummary,
  TimelineResponse,
  TimelineWindow,
  UploadJobResponse,
  UploadStatusResponse,
} from "../types";

export function useAnomalies(
  params: ListAnomaliesParams = {},
  options?: Omit<
    UseQueryOptions<AnomalyListResponse, Error>,
    "queryKey" | "queryFn"
  >,
) {
  return useQuery({
    queryKey: ["anomalies", params],
    queryFn: () => listAnomalies(params),
    // 2s instead of 5s — smoother during a live /connect demo where
    // anomalies arrive at ~2-3/sec. The WebSocket pushes individual
    // events but the list still relies on this poll for full re-render.
    refetchInterval: 2_000,
    ...options,
  });
}

export function useAnomaly(id: string | undefined) {
  return useQuery<Anomaly, Error>({
    queryKey: ["anomaly", id],
    queryFn: () => getAnomaly(id!),
    enabled: !!id,
  });
}

export function useExplanation(
  id: string | undefined,
  status: ExplanationStatus | undefined,
) {
  return useQuery<Explanation | null, Error>({
    queryKey: ["explanation", id],
    queryFn: () => getExplanation(id!),
    enabled: !!id,
    // 500ms (was 2000) — paired with the API-side explanation cache
    // (see backend/api/routes.py::_try_api_cache_hit). The cache lookup
    // resolves a pending GET in <200ms; the next poll picks up the
    // ready Explanation half a second later, making click→display feel
    // instantaneous during the demo.
    refetchInterval: status === "pending" ? 500 : false,
    retry: false,
  });
}

export function useMetricsSummary() {
  return useQuery<MetricsSummary, Error>({
    queryKey: ["metrics-summary"],
    queryFn: getMetricsSummary,
    // KPI strip — 3s feels live during a streaming demo without
    // hammering the API.
    refetchInterval: 3_000,
  });
}

export function useTimeline(window: TimelineWindow) {
  return useQuery<TimelineResponse, Error>({
    queryKey: ["timeline", window],
    queryFn: () => getTimeline(window),
    // 5s on the activity-over-time chart so bars grow smoothly during
    // a /connect demo. 30s was too clumpy.
    refetchInterval: 5_000,
  });
}

export function useDrift() {
  return useQuery<DriftStatus, Error>({
    queryKey: ["drift"],
    queryFn: getDrift,
    refetchInterval: 60_000,
  });
}

export function useHealth() {
  return useQuery<HealthResponse, Error>({
    queryKey: ["health"],
    queryFn: getHealth,
    refetchInterval: 30_000,
    retry: false,
  });
}

export function useFeedback(anomalyId: string) {
  const qc = useQueryClient();
  return useMutation<FeedbackResponse, Error, FeedbackRequest>({
    mutationFn: (body) => postFeedback(anomalyId, body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["anomalies"] });
      qc.invalidateQueries({ queryKey: ["anomaly", anomalyId] });
      // History page should refresh after a new verdict lands.
      qc.invalidateQueries({ queryKey: ["feedback-history"] });
    },
  });
}

export function useFeedbackHistory(limit = 100) {
  return useQuery<FeedbackHistoryResponse, Error>({
    queryKey: ["feedback-history", limit],
    queryFn: () => listFeedback(limit),
    refetchInterval: 30_000,
  });
}

// -- upload ---------------------------------------------------------------

interface UploadVars {
  file: File;
  rate?: number;
}

export function useUpload() {
  return useMutation<UploadJobResponse, Error, UploadVars>({
    mutationFn: ({ file, rate }) => uploadLogFile(file, { rate }),
  });
}

/**
 * Mutation: wipe all anomalies + drift events. Used by the Upload page's
 * "Clear previous anomalies" button so the user can run a fresh test
 * upload without prior data polluting the dashboard.
 *
 * On success, invalidates every dashboard-relevant query so the empty
 * state propagates immediately.
 */
export function useClearAnomalies() {
  const qc = useQueryClient();
  return useMutation<{ deleted: number }, Error, void>({
    mutationFn: () => clearAllAnomalies(),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["anomalies"] });
      qc.invalidateQueries({ queryKey: ["metrics-summary"] });
      qc.invalidateQueries({ queryKey: ["timeline"] });
      qc.invalidateQueries({ queryKey: ["drift"] });
    },
  });
}

/** Polls upload progress every 2 s while running, stops once the
 * server reports a terminal state. Disabled when `jobId` is falsy. */
export function useUploadStatus(jobId: string | null) {
  return useQuery<UploadStatusResponse, Error>({
    queryKey: ["upload-status", jobId],
    queryFn: () => getUploadStatus(jobId!),
    enabled: Boolean(jobId),
    // 2-second cadence per the spec for live progress feedback.
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      if (status === "completed" || status === "failed") return false;
      return 2_000;
    },
    refetchIntervalInBackground: true,
  });
}
