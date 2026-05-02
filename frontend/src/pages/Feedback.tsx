import { useState } from "react";
import { Link } from "react-router-dom";
import { useFeedbackHistory } from "../api/queries";
import { EyebrowLabel } from "../components/EyebrowLabel";
import { cn } from "../lib/cn";
import { formatRelativeTime } from "../lib/format";
import type { Feedback as FeedbackVerdict } from "../types";

/**
 * /feedback — engineer feedback history.
 *
 * Wired to `GET /api/v1/feedback` via `useFeedbackHistory`. Counts
 * (total / true+ / false+) come from the response so they stay
 * consistent with the underlying DB even when the items list is
 * truncated by the backend's limit.
 *
 * Engineer-attribution column is intentionally omitted — the schema
 * doesn't store who-clicked-which-button (auth is single-user for now).
 * Add the column back when multi-user attribution lands.
 */

type Filter = "all" | FeedbackVerdict;

export function Feedback() {
  const [filter, setFilter] = useState<Filter>("all");
  const { data, isLoading, isError, error, refetch } = useFeedbackHistory(200);

  const items = data?.items ?? [];
  const total = data?.total ?? 0;
  const truePos = data?.true_positive ?? 0;
  const falsePos = data?.false_positive ?? 0;
  const precision = total > 0 ? truePos / total : 0;

  const rows =
    filter === "all" ? items : items.filter((r) => r.verdict === filter);

  return (
    <div className="pb-12">
      <header className="mb-7 border-b-[0.5px] border-border-subtle pb-5">
        <EyebrowLabel>Engineer feedback</EyebrowLabel>
        <h1 className="text-[22px] font-medium leading-none tracking-[-0.01em] text-primary">
          Feedback history
        </h1>
      </header>

      {/* Stats strip */}
      <div className="mb-7 grid grid-cols-2 gap-x-8 gap-y-4 md:grid-cols-4">
        <Stat label="Total" value={total.toString()} />
        <Stat label="True positive" value={truePos.toString()} tone="success" />
        <Stat label="False positive" value={falsePos.toString()} tone="critical" />
        <Stat
          label="Precision"
          value={total > 0 ? `${(precision * 100).toFixed(0)}%` : "—"}
          tone="primary"
        />
      </div>

      {/* Filter chips */}
      <div className="mb-4 flex items-center gap-2">
        <FilterChip active={filter === "all"} onClick={() => setFilter("all")}>
          All
        </FilterChip>
        <FilterChip
          active={filter === "true_positive"}
          onClick={() => setFilter("true_positive")}
        >
          True positive
        </FilterChip>
        <FilterChip
          active={filter === "false_positive"}
          onClick={() => setFilter("false_positive")}
        >
          False positive
        </FilterChip>
      </div>

      {/* Loading / error / empty / rows */}
      {isLoading && <StateRow message="Loading feedback history…" />}
      {isError && (
        <StateRow
          message={`Failed to load feedback: ${error?.message ?? "unknown error"}`}
          onRetry={() => refetch()}
        />
      )}
      {!isLoading && !isError && total === 0 && (
        <StateRow message="No feedback submitted yet. Open an anomaly and click True positive / False positive to start." />
      )}
      {!isLoading && !isError && total > 0 && (
        <div className="overflow-hidden rounded-lg border-[0.5px] border-border-subtle bg-card">
          <div className="grid grid-cols-[110px_104px_180px_1fr] items-center gap-4 border-b-[0.5px] border-border-subtle px-4 py-2.5 text-[10px] uppercase tracking-wider text-tertiary">
            <div>Submitted</div>
            <div>Verdict</div>
            <div>Source</div>
            <div>Template</div>
          </div>
          <div className="divide-y-[0.5px] divide-border-subtle">
            {rows.map((r) => (
              <Link
                key={r.anomaly_id}
                to={`/anomalies/${encodeURIComponent(r.anomaly_id)}`}
                className="grid grid-cols-[110px_104px_180px_1fr] items-center gap-4 px-4 py-2.5 transition-colors hover:bg-hover/40"
              >
                <div
                  className="text-[12px] text-tertiary"
                  title={new Date(r.submitted_at).toLocaleString()}
                >
                  {formatRelativeTime(r.submitted_at)}
                </div>
                <div>
                  <VerdictPill verdict={r.verdict} />
                </div>
                <div className="truncate font-mono text-[12px] text-secondary">
                  {r.source}
                </div>
                <div className="truncate font-mono text-[12px] text-primary">
                  {r.log_template}
                </div>
              </Link>
            ))}
            {rows.length === 0 && (
              <div className="px-4 py-6 text-center text-[12px] text-tertiary">
                No feedback matches this filter.
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

function Stat({
  label,
  value,
  tone = "primary",
}: {
  label: string;
  value: string;
  tone?: "primary" | "success" | "critical";
}) {
  return (
    <div>
      <div className="text-[11px] uppercase tracking-wider text-tertiary">
        {label}
      </div>
      <div
        className={cn(
          "mt-1 font-mono text-[20px] tabular-nums",
          tone === "primary" && "text-primary",
          tone === "success" && "text-success",
          tone === "critical" && "text-critical",
        )}
      >
        {value}
      </div>
    </div>
  );
}

function FilterChip({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "rounded-md border-[0.5px] px-3 py-1 text-[11px] transition-colors",
        active
          ? "border-iris/40 bg-iris/10 text-iris"
          : "border-border-subtle bg-card text-secondary hover:bg-hover hover:text-primary",
      )}
    >
      {children}
    </button>
  );
}

function VerdictPill({ verdict }: { verdict: FeedbackVerdict }) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-md border-[0.5px] px-2 py-0.5 text-[10px] uppercase tracking-wider",
        verdict === "true_positive" &&
          "border-success/40 bg-success/10 text-success",
        verdict === "false_positive" &&
          "border-critical/40 bg-critical/10 text-critical",
      )}
    >
      {verdict === "true_positive" ? "true +" : "false +"}
    </span>
  );
}

function StateRow({
  message,
  onRetry,
}: {
  message: string;
  onRetry?: () => void;
}) {
  return (
    <div className="flex flex-col items-center gap-3 rounded-lg border-[0.5px] border-border-subtle bg-card px-4 py-10 text-center text-[12px] text-tertiary">
      <span>{message}</span>
      {onRetry && (
        <button
          type="button"
          onClick={onRetry}
          className="rounded-md border-[0.5px] border-border-subtle px-3 py-1 text-[11px] text-secondary transition-colors hover:bg-hover hover:text-primary"
        >
          Retry
        </button>
      )}
    </div>
  );
}
