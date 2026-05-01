import { useState } from "react";
import { Link } from "react-router-dom";
import { EyebrowLabel } from "../components/EyebrowLabel";
import { cn } from "../lib/cn";
import { formatRelativeTime } from "../lib/format";
import type { Feedback as FeedbackVerdict } from "../types";

/**
 * /feedback — engineer feedback history.
 *
 *   ┌────────────────────────────────────────────────────────────┐
 *   │  Engineer feedback                                         │
 *   │  Feedback history                                          │
 *   ├────────────────────────────────────────────────────────────┤
 *   │  31 total · 23 true · 8 false · 74% precision              │
 *   │  ──────────────────────────────────────────────────────    │
 *   │  [All] [True positive] [False positive]                    │
 *   │                                                            │
 *   │  2m ago   TRUE+    anom_a1b2c3d4   keystone-api  deepthi   │
 *   │  9m ago   FALSE+   anom_e5f6a7b8   neutron-3     alex      │
 *   │  …                                                         │
 *   └────────────────────────────────────────────────────────────┘
 *
 * No real feedback API hookup yet — uses an inline fixture so the page
 * has texture for the demo. When `POST /anomalies/{id}/feedback` is
 * persisted server-side, swap the fixture for a `useFeedbackHistory()`
 * query.
 */

interface FeedbackRecord {
  submitted_at: string;
  verdict: FeedbackVerdict;
  anomaly_id: string;
  source: string;
  template: string;
  engineer: string;
}

function isoMinutesAgo(min: number): string {
  return new Date(Date.now() - min * 60_000)
    .toISOString()
    .replace(/\.\d+Z$/, "Z");
}

const FEEDBACK_HISTORY: FeedbackRecord[] = [
  {
    submitted_at: isoMinutesAgo(2),
    verdict: "true_positive",
    anomaly_id: "anom_a1b2c3d4",
    source: "nova-api-prod-3",
    template: "ERROR keystone-api Failed to authenticate user <*>",
    engineer: "deepthi",
  },
  {
    submitted_at: isoMinutesAgo(9),
    verdict: "false_positive",
    anomaly_id: "anom_e5f6a7b8",
    source: "neutron-server-3",
    template: "WARN slow_query duration=<*>ms",
    engineer: "alex",
  },
  {
    submitted_at: isoMinutesAgo(18),
    verdict: "true_positive",
    anomaly_id: "anom_d4e5f6a7",
    source: "nova-api-prod-7",
    template: "ERROR OOMKilled container terminated <*>",
    engineer: "deepthi",
  },
  {
    submitted_at: isoMinutesAgo(34),
    verdict: "true_positive",
    anomaly_id: "anom_c3d4e5f6",
    source: "glance-api-2",
    template: "ERROR upstream 5xx burst service <*>",
    engineer: "priya",
  },
  {
    submitted_at: isoMinutesAgo(67),
    verdict: "false_positive",
    anomaly_id: "anom_a3b4c5d6",
    source: "prometheus-collector",
    template: "INFO scrape completed targets=<*>",
    engineer: "alex",
  },
  {
    submitted_at: isoMinutesAgo(95),
    verdict: "true_positive",
    anomaly_id: "anom_b8c9d0e1",
    source: "redis-cache-master",
    template: "WARN cache stampede repeated misses key <*>",
    engineer: "deepthi",
  },
  {
    submitted_at: isoMinutesAgo(124),
    verdict: "true_positive",
    anomaly_id: "anom_f6a7b8c9",
    source: "namenode-prod-1",
    template: "WARN heartbeat lost from <*>",
    engineer: "priya",
  },
  {
    submitted_at: isoMinutesAgo(180),
    verdict: "true_positive",
    anomaly_id: "anom_a7b8c9d0",
    source: "nova-api-prod-2",
    template: "WARN rate limit exceeded client <*>",
    engineer: "deepthi",
  },
  {
    submitted_at: isoMinutesAgo(210),
    verdict: "false_positive",
    anomaly_id: "anom_e1f2a3b4",
    source: "nova-api-prod-5",
    template: "INFO request completed status=200 duration=<*>",
    engineer: "alex",
  },
  {
    submitted_at: isoMinutesAgo(265),
    verdict: "true_positive",
    anomaly_id: "anom_c5d6e7f8",
    source: "rabbitmq-1",
    template: "WARN healthcheck failed response code <*>",
    engineer: "deepthi",
  },
];

type Filter = "all" | FeedbackVerdict;

export function Feedback() {
  const [filter, setFilter] = useState<Filter>("all");
  const total = FEEDBACK_HISTORY.length;
  const truePos = FEEDBACK_HISTORY.filter(
    (r) => r.verdict === "true_positive",
  ).length;
  const falsePos = total - truePos;
  const precision = truePos / total;

  const rows =
    filter === "all"
      ? FEEDBACK_HISTORY
      : FEEDBACK_HISTORY.filter((r) => r.verdict === filter);

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
          value={`${(precision * 100).toFixed(0)}%`}
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

      {/* Rows */}
      <div className="overflow-hidden rounded-lg border-[0.5px] border-border-subtle bg-card">
        <div className="grid grid-cols-[110px_104px_180px_1fr_120px] items-center gap-4 border-b-[0.5px] border-border-subtle px-4 py-2.5 text-[10px] uppercase tracking-wider text-tertiary">
          <div>Submitted</div>
          <div>Verdict</div>
          <div>Source</div>
          <div>Template</div>
          <div className="text-right">Engineer</div>
        </div>
        <div className="divide-y-[0.5px] divide-border-subtle">
          {rows.map((r) => (
            <Link
              key={`${r.anomaly_id}-${r.submitted_at}`}
              to={`/anomalies/${encodeURIComponent(r.anomaly_id)}`}
              className="grid grid-cols-[110px_104px_180px_1fr_120px] items-center gap-4 px-4 py-2.5 transition-colors hover:bg-hover/40"
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
                {r.template}
              </div>
              <div className="text-right text-[12px] text-tertiary">
                {r.engineer}
              </div>
            </Link>
          ))}
        </div>
      </div>
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
