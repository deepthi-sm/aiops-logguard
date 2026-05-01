import { Link, useParams } from "react-router-dom";
import { useAnomaly } from "../api/queries";
import { AttentionLines } from "../components/AttentionLines";
import { ErrorState } from "../components/ErrorState";
import { ExplanationCard } from "../components/ExplanationCard";
import { FeedbackButtons } from "../components/FeedbackButtons";
import { ScorePanel } from "../components/ScorePanel";
import { SequencePreview } from "../components/SequencePreview";
import { SeverityPill } from "../components/SeverityPill";
import { Skeleton } from "../components/Skeleton";
import { formatRelativeTime } from "../lib/format";
import type { Anomaly } from "../types";

/**
 * /anomalies/:id — the detail page that makes the demo memorable.
 *
 *   Anomalies / anom_<id>                                    (breadcrumb)
 *
 *   [CRITICAL]  Detected 2m ago  · 14 grouped
 *   <humanised template title>                          [TP]  [FP]
 *   nova-api-prod-3                                       (source mono)
 *   ────────────────────────────────────────────────────
 *   Ensemble │ Confidence │ Failure prob │ Predicted in     (ScorePanel)
 *
 *   ⬢ Root cause analysis  LLaMA 3 · 2 incidents retrieved   (Explanation)
 *   ┌──────────────────────────────────────────────────┐
 *   │ <root cause paragraph>                            │
 *   │                                                   │
 *   │ RECOMMENDED FIX                                   │
 *   │ 1. ...                                            │
 *   │                                                   │
 *   │ SIMILAR PAST INCIDENTS                            │
 *   │ inc_247   ERROR …                       91% match │
 *   └──────────────────────────────────────────────────┘
 *
 *   Top contributing log lines              attention weighted
 *   ▓▓ ERROR keystone-api Failed to authenticate …  0.31
 *   ▒▒ WARN keystone-api elevated auth-fail rate    0.18
 *   ░░ ERROR keystone-api token refresh denied      0.11
 *
 *   ▶ Full sequence (20 events)                              (collapsible)
 */
export function AnomalyDetail() {
  const { id } = useParams<{ id: string }>();
  const { data: anomaly, isLoading, error, refetch } = useAnomaly(id);

  return (
    <div className="pb-12">
      <Breadcrumb id={id} />
      {isLoading && <DetailSkeleton />}
      {error && (
        <ErrorState message={(error as Error).message} onRetry={() => refetch()} />
      )}
      {anomaly && <DetailBody anomaly={anomaly} />}
    </div>
  );
}

// -- Breadcrumb ------------------------------------------------------------

function Breadcrumb({ id }: { id: string | undefined }) {
  return (
    <div className="mb-3 text-[11px] text-tertiary">
      <Link
        to="/anomalies"
        className="transition-colors hover:text-secondary"
      >
        Anomalies
      </Link>
      <span aria-hidden className="mx-1.5 text-muted">
        /
      </span>
      <span className="font-mono text-secondary">{id ?? "—"}</span>
    </div>
  );
}

// -- Header + body --------------------------------------------------------

function DetailBody({ anomaly }: { anomaly: Anomaly }) {
  return (
    <>
      <Header anomaly={anomaly} />
      <ScorePanel anomaly={anomaly} />
      <ExplanationCard
        anomalyId={anomaly.id}
        status={anomaly.explanation_status}
      />
      <AttentionLines lines={anomaly.top_contributing_lines} />
      <SequencePreview
        lines={anomaly.sequence_preview}
        contributingLines={anomaly.top_contributing_lines}
      />
    </>
  );
}

function Header({ anomaly }: { anomaly: Anomaly }) {
  const cluster = anomaly.cluster_size > 1 ? `${anomaly.cluster_size} grouped` : null;
  return (
    <header className="mb-7 flex items-start justify-between gap-4 border-b-[0.5px] border-border-subtle pb-5">
      <div className="min-w-0 flex-1">
        <div className="mb-3 flex flex-wrap items-center gap-3">
          <SeverityPill severity={anomaly.severity} />
          <span className="text-[11px] text-tertiary">
            Detected {formatRelativeTime(anomaly.detected_at)}
          </span>
          {cluster && (
            <>
              <span aria-hidden className="text-[11px] text-tertiary">
                ·
              </span>
              <span className="text-[11px] text-tertiary">{cluster}</span>
            </>
          )}
        </div>
        <h1 className="break-words text-[22px] font-medium leading-tight tracking-[-0.01em] text-primary">
          {humaniseTemplate(anomaly.log_template)}
        </h1>
        <div className="mt-1.5 font-mono text-[12px] text-tertiary">
          {anomaly.source}
        </div>
      </div>
      <div className="shrink-0">
        <FeedbackButtons anomalyId={anomaly.id} />
      </div>
    </header>
  );
}

/**
 * Strip Drain3 placeholders ("<*>", "<IP>", etc.) and clamp at ~60 chars
 * so the title is readable without losing meaning.
 */
function humaniseTemplate(template: string): string {
  const cleaned = template
    .replace(/<\*>/g, "*")
    .replace(/<[A-Z_]+>/g, "*")
    .replace(/\s+/g, " ")
    .trim();
  return cleaned.length > 60 ? `${cleaned.slice(0, 57)}…` : cleaned;
}

// -- Skeleton --------------------------------------------------------------

function DetailSkeleton() {
  return (
    <div>
      <Skeleton className="mb-2 h-3 w-24 bg-card" />
      <div className="mb-7 border-b-[0.5px] border-border-subtle pb-5">
        <Skeleton className="mb-3 h-3 w-40 bg-card" />
        <Skeleton className="mb-2 h-7 w-2/3 bg-card" />
        <Skeleton className="h-3 w-32 bg-card" />
      </div>
      <div className="mb-7 flex gap-7">
        {[0, 1, 2, 3].map((i) => (
          <div key={i} className="flex-1">
            <Skeleton className="mb-2 h-3 w-24 bg-card" />
            <Skeleton className="h-9 w-16 bg-card" />
          </div>
        ))}
      </div>
      <Skeleton className="mb-7 h-48 bg-card" />
      <Skeleton className="mb-7 h-32 bg-card" />
    </div>
  );
}
