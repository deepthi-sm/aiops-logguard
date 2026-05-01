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
  listAnomalies,
  postFeedback,
  type ListAnomaliesParams,
} from "./client";
import type {
  Anomaly,
  AnomalyListResponse,
  DriftStatus,
  Explanation,
  ExplanationStatus,
  FeedbackRequest,
  FeedbackResponse,
  HealthResponse,
  MetricsSummary,
  TimelineResponse,
  TimelineWindow,
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
    },
  });
}
