import { Link } from "react-router-dom";
import { cn } from "../lib/cn";
import { formatRelativeTime, formatScore } from "../lib/format";
import { severityBgClassName, severityClassName } from "../lib/severity";
import type { Anomaly } from "../types";
import { LogLine } from "./LogLine";

/**
 * One row in the dashboard's "Recent activity" feed. Per spec:
 *
 *   ▌  ERROR keystone-api Failed to authenticate user <*> from <IP>     94%
 *      nova-api-prod-3 · 2m ago · ×14
 *
 * Severity color appears ONLY on the left rail and the right-side score —
 * not on the row background (spec rule #10). Whole row is a clickable link.
 */
export function AnomalyFeedRow({ anomaly }: { anomaly: Anomaly }) {
  const showCluster = anomaly.cluster_size > 1;
  return (
    <Link
      to={`/anomalies/${encodeURIComponent(anomaly.id)}`}
      className="group flex items-center gap-3 py-3 transition-colors hover:bg-hover/40"
    >
      <div
        className={cn(
          "h-8 w-[3px] shrink-0 rounded-sm",
          severityBgClassName(anomaly.severity),
        )}
        aria-hidden
      />

      <div className="min-w-0 flex-1">
        <LogLine
          line={anomaly.log_template}
          className="block truncate text-[13px] text-primary"
        />
        <div className="mt-1 flex items-center gap-2 font-mono text-[11px] text-tertiary">
          <span className="truncate">{anomaly.source}</span>
          <span aria-hidden>·</span>
          <span>{formatRelativeTime(anomaly.detected_at)}</span>
          {showCluster && (
            <>
              <span aria-hidden>·</span>
              <span>×{anomaly.cluster_size}</span>
            </>
          )}
        </div>
      </div>

      <div
        className={cn(
          "shrink-0 font-mono text-[14px] tabular-nums",
          severityClassName(anomaly.severity),
        )}
      >
        {/* digits=2 — see AnomalyTable for the same reason. The
            saturated tail (>0.99) collapses to "100%" with the
            default 0 decimals; two decimals shows the true variation. */}
        {formatScore(anomaly.ensemble_score, 2)}
      </div>
    </Link>
  );
}
