import { Link } from "react-router-dom";
import { useAnomalies, useDrift, useMetricsSummary } from "../api/queries";
import { AnomalyFeedRow } from "../components/AnomalyFeedRow";
import { ConfidenceChart } from "../components/ConfidenceChart";
import { EmptyState } from "../components/EmptyState";
import { ErrorState } from "../components/ErrorState";
import { EyebrowLabel } from "../components/EyebrowLabel";
import { KpiBar } from "../components/KpiBar";
import { KpiCell } from "../components/KpiCell";
import { Skeleton } from "../components/Skeleton";
import { TimelineChart } from "../components/TimelineChart";
import { cn } from "../lib/cn";
import { formatRelativeTime, formatScore } from "../lib/format";
import { driftClassName, driftLabel } from "../lib/severity";
import type { Anomaly, DriftStatus, MetricsSummary } from "../types";

/**
 * Dashboard (`/`) — the demo's centrepiece. Per spec:
 *
 *   ┌────────────────────────────────────────────────────────────────┐
 *   │ Anomaly intelligence (eyebrow)                                  │
 *   │ Live dashboard (title)                  Updated · ● Live        │
 *   ├────────────────────────────────────────────────────────────────┤
 *   │ Past 24h │ Critical │ Confidence │ Drift                        │
 *   │   142    │    3     │    84%     │  0.12                        │
 *   ├────────────────────────────────────────────────────────────────┤
 *   │ Activity over time                            [1h] [24h] [7d]   │
 *   │ ▁▂▆▃▅▂▁▁▂▃ stacked critical/warning/info                       │
 *   ├────────────────────────────────────────────────────────────────┤
 *   │ Recent activity                              view all →         │
 *   │ ▌ ERROR keystone-api Failed …          nova-api-prod-3  94%    │
 *   │ ▌ WARN slow_query duration=…           neutron-server-3 74%    │
 *   │ ▌ …                                                              │
 *   └────────────────────────────────────────────────────────────────┘
 */
export function Dashboard() {
  const summary = useMetricsSummary();
  const drift = useDrift();
  const recent = useAnomalies({ limit: 5 });
  // For the confidence trend chart — last 100 anomalies, newest first.
  const recentLarge = useAnomalies({ limit: 100 });

  // The most recent successful refetch among the four queries — used by
  // the header's "Updated X ago" line so it tracks reality, not a fixed
  // string.
  const lastUpdated = Math.max(
    summary.dataUpdatedAt,
    drift.dataUpdatedAt,
    recent.dataUpdatedAt,
    recentLarge.dataUpdatedAt,
  );

  return (
    <div className="pb-12">
      <Header lastUpdatedMs={lastUpdated} />
      <KpiSection
        summary={summary.data}
        drift={drift.data}
        loading={summary.isLoading || drift.isLoading}
      />
      <TimelineChart />
      <ConfidenceChart
        items={recentLarge.data?.items ?? []}
        loading={recentLarge.isLoading}
      />
      <RecentActivity
        items={recent.data?.items ?? []}
        loading={recent.isLoading}
        error={recent.error as Error | null}
        onRetry={() => recent.refetch()}
      />
    </div>
  );
}

// -- Header ----------------------------------------------------------------

function Header({ lastUpdatedMs }: { lastUpdatedMs: number }) {
  // Fall back to "—" until at least one query has resolved (otherwise
  // we'd flash "55 years ago" off the unix epoch).
  const updatedLabel =
    lastUpdatedMs > 0
      ? `Updated ${formatRelativeTime(new Date(lastUpdatedMs).toISOString())}`
      : "Updated —";
  return (
    <header className="mb-7 flex items-end justify-between border-b-[0.5px] border-border-subtle pb-5">
      <div>
        <EyebrowLabel>Anomaly intelligence</EyebrowLabel>
        <h1 className="text-[22px] font-medium leading-none tracking-[-0.01em] text-primary">
          Live dashboard
        </h1>
      </div>
      <div className="flex items-center gap-2 text-[11px] text-tertiary">
        <span title={lastUpdatedMs > 0 ? new Date(lastUpdatedMs).toLocaleString() : ""}>
          {updatedLabel}
        </span>
        <span aria-hidden>·</span>
        <span className="flex items-center gap-1.5">
          <span className="relative inline-flex h-1.5 w-1.5">
            <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-success opacity-50" />
            <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-success" />
          </span>
          Live
        </span>
      </div>
    </header>
  );
}

// -- KPI section -----------------------------------------------------------

function KpiSection({
  summary,
  drift,
  loading,
}: {
  summary: MetricsSummary | undefined;
  drift: DriftStatus | undefined;
  loading: boolean;
}) {
  if (loading || !summary) {
    return <KpiBarSkeleton />;
  }
  return (
    <KpiBar>
      <KpiCell
        eyebrow="Past 24 hours"
        value={<span className="font-mono">{summary.total_24h}</span>}
        subLabel="total anomalies"
      />
      <KpiCell
        eyebrow="Critical"
        value={<span className="font-mono">{summary.critical_24h}</span>}
        valueClassName="text-critical"
        subLabel={`${summary.critical_24h} unack`}
      />
      <KpiCell
        eyebrow="Confidence"
        value={
          <span className="font-mono">
            {formatScore(summary.avg_confidence, 0)}
          </span>
        }
        subLabel="model average"
      />
      <KpiCell
        eyebrow="Drift"
        value={
          <span
            className={cn(
              "font-mono",
              drift && driftClassName(drift.status),
            )}
          >
            {drift ? drift.drift_score.toFixed(2) : "—"}
          </span>
        }
        subLabel={drift ? driftLabel(drift.status) : "loading"}
      />
    </KpiBar>
  );
}

function KpiBarSkeleton() {
  return (
    <div className="mb-7 flex gap-7">
      {[0, 1, 2, 3].map((i) => (
        <div key={i} className="flex-1">
          <Skeleton className="mb-2 h-3 w-24 bg-hover" />
          <Skeleton className="mb-2 h-9 w-16 bg-hover" />
          <Skeleton className="h-3 w-20 bg-hover" />
        </div>
      ))}
    </div>
  );
}

// -- Recent activity feed --------------------------------------------------

function RecentActivity({
  items,
  loading,
  error,
  onRetry,
}: {
  items: Anomaly[];
  loading: boolean;
  error: Error | null;
  onRetry: () => void;
}) {
  return (
    <section>
      <div className="mb-[14px] flex items-end justify-between">
        <h2 className="text-[13px] font-medium text-primary">
          Recent activity
        </h2>
        <Link
          to="/anomalies"
          className="text-[11px] text-iris transition-colors hover:text-iris-deep"
        >
          view all →
        </Link>
      </div>

      <div className="rounded-lg border-[0.5px] border-border-subtle bg-card px-5">
        {loading && (
          <div className="space-y-3 py-3">
            {[0, 1, 2, 3, 4].map((i) => (
              <Skeleton key={i} className="h-8 bg-hover" />
            ))}
          </div>
        )}
        {error && (
          <ErrorState message={error.message} onRetry={onRetry} />
        )}
        {!loading && !error && items.length === 0 && (
          <EmptyState message="No anomalies in the last hour — system is healthy." />
        )}
        {!loading && !error && items.length > 0 && (
          <div className="divide-y divide-border-subtle">
            {items.slice(0, 5).map((a) => (
              <AnomalyFeedRow key={a.id} anomaly={a} />
            ))}
          </div>
        )}
      </div>
    </section>
  );
}
