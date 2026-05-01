/**
 * TanStack Query hooks — automatic caching, refetching, loading states.
 *
 * Query keys are namespaced so related cache invalidations are easy
 * (e.g. after a feedback POST we invalidate `["anomalies"]` to refresh).
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
} from "../api/client";
import type {
  Anomaly,
  AnomalyListResponse,
  DriftStatus,
  Explanation,
  FeedbackRequest,
  FeedbackResponse,
  HealthResponse,
  MetricsSummary,
  TimelineResponse,
  TimelineWindow,
} from "../api/types";

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
    refetchInterval: 5_000, // soft auto-refresh in addition to WS pushes
    ...options,
  });
}

export function useAnomaly(id: string | null) {
  return useQuery<Anomaly, Error>({
    queryKey: ["anomaly", id],
    queryFn: () => getAnomaly(id!),
    enabled: !!id,
  });
}

export function useExplanation(id: string | null, status?: string) {
  return useQuery<Explanation | null, Error>({
    queryKey: ["explanation", id],
    queryFn: () => getExplanation(id!),
    enabled: !!id,
    // If the anomaly is "pending", poll every 5 seconds until ready.
    refetchInterval: status === "pending" ? 5_000 : false,
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
      // Invalidate so the anomaly's status (if shown) is refreshed.
      qc.invalidateQueries({ queryKey: ["anomalies"] });
      qc.invalidateQueries({ queryKey: ["anomaly", anomalyId] });
    },
  });
}
