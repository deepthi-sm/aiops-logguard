import { Link } from "react-router-dom";
import { cn } from "../lib/cn";
import { formatNumber, formatRelativeTime, formatScore } from "../lib/format";
import type { Anomaly } from "../types";
import { LogLine } from "./LogLine";
import { SeverityPill } from "./SeverityPill";

interface AnomalyTableProps {
  items: Anomaly[];
  /** When true, additional rows in a collapsed cluster show a "view N grouped" affordance. */
  showClusterAffordance?: boolean;
}

/**
 * Anomaly table per spec:
 *
 *   Time      Severity   Source              Template (truncated)        Conf    Cluster
 *   2m ago    [CRIT]     nova-api-prod-3     ERROR keystone Failed …     0.91    14
 *   3m ago    [CRIT]     neutron-server-1    ERROR connection pool …     0.86    7
 *   …
 *
 * Each row is a `<Link to="/anomalies/:id">` so any click navigates.
 * Sticky header — stays visible during scroll. Mono / tabular-nums on
 * Confidence and Cluster columns. Time hover-tooltip shows the absolute
 * timestamp.
 */
export function AnomalyTable({ items, showClusterAffordance = true }: AnomalyTableProps) {
  return (
    <div className="overflow-hidden rounded-lg border-[0.5px] border-border-subtle bg-card">
      {/* Header */}
      <div className="sticky top-0 z-10 grid grid-cols-[110px_88px_180px_1fr_72px_72px] items-center gap-4 border-b-[0.5px] border-border-subtle bg-card px-4 py-2.5 text-[10px] uppercase tracking-wider text-tertiary">
        <div>Time</div>
        <div>Severity</div>
        <div>Source</div>
        <div>Template</div>
        <div className="text-right">Conf</div>
        <div className="text-right">Cluster</div>
      </div>

      {/* Rows */}
      <div className="divide-y divide-border-subtle">
        {items.map((a) => (
          <Link
            key={a.id}
            to={`/anomalies/${encodeURIComponent(a.id)}`}
            className="grid grid-cols-[110px_88px_180px_1fr_72px_72px] items-center gap-4 px-4 py-2.5 transition-colors hover:bg-hover/40"
          >
            <div
              className="text-[12px] text-tertiary"
              title={new Date(a.detected_at).toLocaleString()}
            >
              {formatRelativeTime(a.detected_at)}
            </div>
            <div>
              <SeverityPill severity={a.severity} />
            </div>
            <div className="truncate font-mono text-[12px] text-secondary">
              {a.source}
            </div>
            <LogLine
              line={a.log_template}
              className="truncate font-mono text-[12px] text-primary"
            />
            <div
              className={cn(
                "text-right font-mono text-[12px] tabular-nums",
                "text-primary",
              )}
            >
              {/* digits=2 — saturated cross-domain anomalies cluster
                  in a tight confidence band (e.g. 0.6627–0.6632 on
                  BGL through the OpenStack model). 0-decimal "%"
                  rounds them all to "66%" and the table reads as
                  hardcoded. Two decimals exposes the variation. */}
              {formatScore(a.confidence, 2)}
            </div>
            <div className="text-right font-mono text-[12px] tabular-nums text-tertiary">
              {showClusterAffordance && a.cluster_size > 1 ? (
                <span className="rounded-md border-[0.5px] border-border-subtle bg-page px-1.5 py-0.5">
                  ×{formatNumber(a.cluster_size)}
                </span>
              ) : (
                formatNumber(a.cluster_size)
              )}
            </div>
          </Link>
        ))}
      </div>
    </div>
  );
}
