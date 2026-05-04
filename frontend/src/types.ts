/**
 * LogGuard API types — shape mirror of `backend/api/schemas.py` (Pydantic).
 *
 * For now these are hand-written from the design spec's "Anomaly object shape"
 * section. When the backend is reachable, run:
 *
 *     npm run generate-types
 *
 * which writes a real `src/api/generated.ts` from `/openapi.json`. After that,
 * this file should be replaced with `export * from "./api/generated";` (and
 * any name remappings if openapi-typescript's `components["schemas"]["X"]`
 * style is preferred over flat type aliases).
 *
 * Until then, the contract is: ANY change to backend schemas must be
 * mirrored here. Type errors at the call sites are the safety net.
 */

export type Severity = "critical" | "warning" | "info";
export type ExplanationStatus = "pending" | "ready" | "failed";
export type Feedback = "true_positive" | "false_positive";
export type TimelineWindow = "1h" | "24h" | "7d";
export type DriftLevel = "healthy" | "drift_high" | "drift_critical";
// Entry-point tag for filtering; distinct from `source` (parsed display name).
//   "live-stream" — emitted by the live ingestion runner
//   "user-upload" — emitted by a /upload streaming job
export type Origin = "live-stream" | "user-upload";

export interface ContributingLine {
  line: string;
  attention: number; // 0..1
}

export interface Anomaly {
  id: string; // anom_<iso>_<4hex>
  detected_at: string; // ISO 8601 UTC with 'Z' suffix
  severity: Severity;
  source: string;
  origin: Origin;
  ensemble_score: number; // 0..1
  confidence: number; // 0..1
  failure_probability: number; // 0..1
  predicted_failure_window_min: number | null;
  log_template: string;
  sequence_preview: string[];
  top_contributing_lines: ContributingLine[];
  explanation_status: ExplanationStatus;
  cluster_id: string;
  cluster_size: number;
}

export interface AnomalyListResponse {
  items: Anomaly[];
  next_cursor: string | null;
}

export interface SimilarIncident {
  incident_id: string;
  template: string;
  resolved_at: string | null;
  similarity_score: number;
}

export interface Explanation {
  root_cause: string;
  recommended_fix: string;
  similar_incidents: SimilarIncident[];
  attention_weights: number[];
}

export interface MetricsSummary {
  total_24h: number;
  critical_24h: number;
  warning_24h: number;
  info_24h: number;
  avg_confidence: number;
  drift_score: number;
  last_retrain: string | null;
}

export interface TimelineBucket {
  ts: string;
  critical: number;
  warning: number;
  info: number;
}

export interface TimelineResponse {
  window: TimelineWindow;
  buckets: TimelineBucket[];
}

export interface DriftStatus {
  drift_score: number;
  last_retrain: string | null;
  status: DriftLevel;
  psi_score: number;
  // Optional, default false on older API responses. True when the
  // score is a synthetic proxy (std-dev of recent confidences) rather
  // than a real PSI from a `drift_events` row.
  is_synthetic?: boolean;
}

export interface FeedbackRequest {
  feedback: Feedback;
}

export interface FeedbackResponse {
  ok: boolean;
}

export interface FeedbackHistoryItem {
  anomaly_id: string;
  verdict: Feedback;
  submitted_at: string; // ISO 8601 UTC; backend uses detected_at as proxy.
  source: string;
  log_template: string;
  severity: Severity;
  // Postmortem snippet from the RAG worker. Empty string when the
  // explainer hasn't run yet (still pending / failed). The Incidents
  // page falls back to log_template when blank.
  root_cause?: string;
}

export interface FeedbackHistoryResponse {
  items: FeedbackHistoryItem[];
  total: number;
  true_positive: number;
  false_positive: number;
}

// -- System services + queue ---------------------------------------------

export type ServiceStatus = "online" | "degraded" | "offline";

export interface SystemService {
  name: string;
  status: ServiceStatus;
  detail: string;
}

export interface SystemServicesResponse {
  items: SystemService[];
}

export interface SystemQueueResponse {
  pending: number;
  ready: number;
  failed: number;
  oldest_pending_id: string | null;
  oldest_pending_at: string | null;
}

// -- Training runs --------------------------------------------------------

export type TrainingRunStatus = "active" | "completed" | "failed";

export interface TrainingRun {
  id: number;
  started_at: string;        // ISO 8601 UTC
  completed_at: string | null;
  dataset: string;
  f1_score: number | null;
  precision_score: number | null;
  recall_score: number | null;
  artifacts_path: string | null;
  notes: string;
  status: TrainingRunStatus;
}

export interface TrainingRunsResponse {
  items: TrainingRun[];
  active_id: number | null;
}

// -- Upload ---------------------------------------------------------------

export type UploadStatus = "queued" | "running" | "completed" | "failed";

export interface UploadJobResponse {
  job_id: string;
  total_lines: number;
  rate: number;
  status: UploadStatus;
}

export interface UploadStatusResponse {
  job_id: string;
  status: UploadStatus;
  lines_streamed: number;
  total_lines: number;
  eta_seconds: number | null;
  error: string | null;
}

export interface HealthResponse {
  status: "ok" | "degraded";
  version: string;
  uptime_s: number;
}

// -- WebSocket envelopes --------------------------------------------------

export type WsMessage =
  | { type: "anomaly"; data: Anomaly }
  | {
      type: "explanation_ready";
      data: { anomaly_id: string; explanation_status: ExplanationStatus };
    }
  | { type: "ping" };
