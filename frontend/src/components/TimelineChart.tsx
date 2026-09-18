import { useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
  type TooltipProps,
} from "recharts";
import { useTimeline } from "../api/queries";
import { cn } from "../lib/cn";
import type { TimelineWindow } from "../types";
import { EmptyState } from "./EmptyState";
import { Skeleton } from "./Skeleton";

const WINDOW_OPTIONS: { value: TimelineWindow; label: string }[] = [
  { value: "1h", label: "1h" },
  { value: "24h", label: "24h" },
  { value: "7d", label: "7d" },
];

/**
 * Stacked bar chart of anomaly counts per time bucket.
 *
 * Per spec:
 *   - Stack order: critical (top) → warning → info (bottom). Recharts
 *     stacks the FIRST `<Bar>` at the bottom, so render in reverse.
 *   - Bar widths ~14px with 4px gap (small-multiples editorial look).
 *   - Y-axis hidden, X-axis hidden.
 *   - Hover tooltip shows the bucket time + per-severity counts in mono.
 */
export function TimelineChart() {
  const [window, setWindow] = useState<TimelineWindow>("24h");
  const { data, isLoading, error } = useTimeline(window);

  return (
    <section className="mb-7">
      <div className="mb-[14px] flex items-end justify-between">
        <h2 className="text-[13px] font-medium text-primary">
          Activity over time
        </h2>
        <WindowToggle value={window} onChange={setWindow} />
      </div>

      <div className="rounded-lg border-[0.5px] border-border-subtle bg-card p-5">
        {isLoading && <Skeleton className="h-[200px] bg-hover" />}
        {error && (
          <div className="flex h-[200px] items-center justify-center text-[12px] text-tertiary">
            Failed to load timeline.
          </div>
        )}
        {data && allBucketsZero(data.buckets) && (
          <EmptyState message="No anomalies recorded in this time window — system is healthy." />
        )}
        {data && data.buckets.length > 0 && !allBucketsZero(data.buckets) && (
          <div style={{ width: "100%", height: 220 }}>
            <ResponsiveContainer>
              <BarChart
                data={data.buckets}
                barCategoryGap={2}
                margin={{ top: 8, right: 8, bottom: 4, left: 8 }}
              >
                <CartesianGrid
                  strokeDasharray="3 3"
                  stroke="var(--border-subtle)"
                  vertical={false}
                />
                <XAxis
                  dataKey="ts"
                  stroke="var(--text-tertiary)"
                  tick={{ fill: "var(--text-tertiary)", fontSize: 10 }}
                  tickFormatter={(ts: string) => formatBucketTick(ts, window)}
                  minTickGap={32}
                  label={{
                    value: window === "1h" ? "Time (UTC)" : "Bucket start (UTC)",
                    position: "insideBottom",
                    offset: -2,
                    style: { fill: "var(--text-tertiary)", fontSize: 10 },
                  }}
                />
                <YAxis
                  stroke="var(--text-tertiary)"
                  tick={{ fill: "var(--text-tertiary)", fontSize: 10 }}
                  allowDecimals={false}
                  // 56 px so 4-digit tick labels (e.g. "1200") and the
                  // rotated "Anomalies" axis label stop fighting for
                  // the same channel — the previous 36 px width caused
                  // them to overlap once anomaly counts hit 4 digits.
                  width={56}
                  label={{
                    value: "Anomalies",
                    angle: -90,
                    position: "insideLeft",
                    offset: 0,
                    style: { fill: "var(--text-tertiary)", fontSize: 10 },
                  }}
                />
                {/* Stack order is bottom -> top, so info first, critical last. */}
                <Bar
                  dataKey="info"
                  stackId="a"
                  fill="var(--severity-info)"
                  radius={[1, 1, 0, 0]}
                  isAnimationActive={false}
                />
                <Bar
                  dataKey="warning"
                  stackId="a"
                  fill="var(--severity-warning)"
                  radius={[1, 1, 0, 0]}
                  isAnimationActive={false}
                />
                <Bar
                  dataKey="critical"
                  stackId="a"
                  fill="var(--severity-critical)"
                  radius={[1, 1, 0, 0]}
                  isAnimationActive={false}
                />
                <Tooltip
                  cursor={{ fill: "var(--bg-hover)", opacity: 0.6 }}
                  content={<TimelineTooltip />}
                />
              </BarChart>
            </ResponsiveContainer>
          </div>
        )}
      </div>
    </section>
  );
}

function WindowToggle({
  value,
  onChange,
}: {
  value: TimelineWindow;
  onChange: (v: TimelineWindow) => void;
}) {
  return (
    <div className="flex gap-1 rounded-md border-[0.5px] border-border-subtle bg-card p-0.5">
      {WINDOW_OPTIONS.map((o) => (
        <button
          key={o.value}
          type="button"
          onClick={() => onChange(o.value)}
          className={cn(
            "rounded px-2 py-0.5 text-[11px] transition-colors",
            value === o.value
              ? "bg-hover text-primary"
              : "text-tertiary hover:text-secondary",
          )}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

function allBucketsZero(buckets: { critical: number; warning: number; info: number }[]) {
  return buckets.every((b) => b.critical === 0 && b.warning === 0 && b.info === 0);
}

function formatBucketTick(ts: string, window: TimelineWindow): string {
  const d = new Date(ts);
  if (window === "1h") {
    return d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
  }
  if (window === "24h") {
    return d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
  }
  // 7d window
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}


function TimelineTooltip({ active, payload, label }: TooltipProps<number, string>) {
  if (!active || !payload || payload.length === 0) return null;
  const ts = label as string | number | undefined;
  const formatted = ts
    ? new Date(typeof ts === "string" ? ts : Number(ts)).toLocaleString(
        undefined,
        { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" },
      )
    : "";
  // Recharts gives newest-first by default in stacked tooltips; reverse so
  // critical shows on top in the tooltip too.
  const ordered = [...payload].reverse();
  return (
    <div className="rounded-md border-[0.5px] border-border-default bg-card px-3 py-2 shadow-none">
      <div className="mb-1 text-[10px] uppercase tracking-wider text-tertiary">
        {formatted}
      </div>
      {ordered.map((p) => (
        <div
          key={p.dataKey as string}
          className="flex items-center justify-between gap-4 text-[11px]"
        >
          <span className="capitalize text-secondary">
            {String(p.dataKey)}
          </span>
          <span
            className="font-mono tabular-nums"
            style={{ color: p.color as string | undefined }}
          >
            {p.value}
          </span>
        </div>
      ))}
    </div>
  );
}
