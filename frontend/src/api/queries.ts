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
  getSystemQueue,
  getSystemServices,
  getTimeline,
  getUploadStatus,
  listAnomalies,
  listFeedback,
  listTrainingRuns,
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
  SystemQueueResponse,
  SystemServicesResponse,
  TimelineResponse,
  TimelineWindow,
  TrainingRunsResponse,
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
    // Poll the anomaly itself while its explanation is being
    // generated, so the parent component sees `explanation_status`
    // flip from "pending" → "ready" / "failed" without the user
    // having to reload the page. Without this, the AnomalyDetail
    // page would load the row once with status="pending" and never
    // re-fetch, leaving the rendered status frozen even though
    // useExplanation has already pulled the finished explanation
    // from the API. 2 s cadence matches the dashboard list.
    refetchInterval: (query) => {
      const data = query.state.data;
      return data?.explanation_status === "pending" ? 2_000 : false;
    },
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
    // 500 ms while the parent says pending AND we don't yet have a
    // generated explanation. The moment the API returns 200 with
    // data we stop polling — there is no point re-fetching the same
    // payload every half-second until useAnomaly's next tick refreshes
    // the parent's status prop. (Without the early stop, polling
    // continued indefinitely, which is why "load only after refresh"
    // looked like the page was stuck.)
    refetchInterval: (query) => {
      if (query.state.data) return false;
      return status === "pending" ? 500 : false;
    },
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

export function useSystemServices() {
  return useQuery<SystemServicesResponse, Error>({
    queryKey: ["system-services"],
    queryFn: getSystemServices,
    // 10 s — service-state changes (Postgres up/down, Ollama
    // unreachable) need a faster cadence than the 30 s health endpoint
    // we also poll, but not so fast we DDOS the probes.
    refetchInterval: 10_000,
  });
}

export function useSystemQueue() {
  return useQuery<SystemQueueResponse, Error>({
    queryKey: ["system-queue"],
    queryFn: getSystemQueue,
    // 5 s — queue depth changes second-by-second during a /connect or
    // /upload run; this cadence is fast enough to look live without
    // hammering the DB.
    refetchInterval: 5_000,
  });
}

export function useTrainingRuns(limit = 50) {
  return useQuery<TrainingRunsResponse, Error>({
    queryKey: ["training-runs", limit],
    queryFn: () => listTrainingRuns(limit),
    // Training runs are immutable once written — refresh once a minute
    // is plenty (covers the case where a CI run drops a new row while
    // the user has the page open).
    refetchInterval: 60_000,
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
