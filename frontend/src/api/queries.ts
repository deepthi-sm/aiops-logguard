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
    refetchInterval: 5_000,
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
    refetchInterval: status === "pending" ? 2_000 : false,
    retry: false,
  });
}

export function useMetricsSummary() {
  return useQuery<MetricsSummary, Error>({
    queryKey: ["metrics-summary"],
    queryFn: getMetricsSummary,
    refetchInterval: 10_000,
  });
}

export function useTimeline(window: TimelineWindow) {
  return useQuery<TimelineResponse, Error>({
    queryKey: ["timeline", window],
    queryFn: () => getTimeline(window),
    refetchInterval: 30_000,
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
