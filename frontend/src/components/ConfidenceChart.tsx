import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
  type TooltipProps,
} from "recharts";
import { EmptyState } from "./EmptyState";
import { Skeleton } from "./Skeleton";
import type { Anomaly } from "../types";

/**
 * Line chart of confidence-per-anomaly over the last N detections.
 *
 * Reads the last 100 anomalies (passed in by the dashboard) sorted
 * oldest -> newest along the X axis. Y axis is confidence in [0, 1].
 * Hover shows the anomaly id + full ISO timestamp + confidence value.
 *
 * Empty / loading / "all zero confidence" states render a friendly
 * message instead of a broken empty axis. The "all-zero" case is
 * worth its own message because it usually means the confidence MLP
 * needs retraining (it shouldn't ever produce a flat-zero distribution).
 */
interface Props {
  items: Anomaly[];
  loading: boolean;
}

interface DataPoint {
  index: number;
  confidence: number;
  anomalyId: string;
  detectedAt: string;
}

export function ConfidenceChart({ items, loading }: Props) {
  return (
    <section className="mb-7">
      <div className="mb-[14px] flex items-end justify-between">
        <h2 className="text-[13px] font-medium text-primary">
          Confidence over the last {items.length || 100} anomalies
        </h2>
        <span className="text-[11px] text-tertiary">
          model confidence · 0 to 1
        </span>
      </div>

      <div className="rounded-lg border-[0.5px] border-border-subtle bg-card p-5">
        {loading && <Skeleton className="h-[200px] bg-hover" />}
        {!loading && items.length === 0 && (
          <EmptyState message="No anomalies yet — the confidence chart will populate once detections start arriving." />
        )}
        {!loading && items.length > 0 && <ChartBody items={items} />}
      </div>
    </section>
  );
}

function ChartBody({ items }: { items: Anomaly[] }) {
  // Newest-first comes from the API; reverse so the X axis reads
  // left-to-right oldest -> newest, which matches every other timeline
  // in the app.
  const data: DataPoint[] = items
    .slice()
    .reverse()
    .map((a, i) => ({
      index: i,
      confidence: a.confidence,
      anomalyId: a.id,
      detectedAt: a.detected_at,
    }));

  return (
    <div style={{ width: "100%", height: 200 }}>
      <ResponsiveContainer>
        <LineChart
          data={data}
          margin={{ top: 8, right: 16, bottom: 4, left: 0 }}
        >
          <CartesianGrid
            strokeDasharray="3 3"
            stroke="var(--border-subtle)"
            vertical={false}
          />
          <XAxis
            dataKey="index"
            stroke="var(--text-tertiary)"
            tick={{ fill: "var(--text-tertiary)", fontSize: 10 }}
            tickFormatter={(v: number) => `#${v + 1}`}
            label={{
              value: "Anomaly (oldest -> newest)",
              position: "insideBottom",
              offset: -2,
              style: { fill: "var(--text-tertiary)", fontSize: 10 },
            }}
          />
          <YAxis
            domain={[0, 1]}
            ticks={[0, 0.25, 0.5, 0.75, 1]}
            stroke="var(--text-tertiary)"
            tick={{ fill: "var(--text-tertiary)", fontSize: 10 }}
            tickFormatter={(v: number) => v.toFixed(2)}
            label={{
              value: "Confidence",
              angle: -90,
              position: "insideLeft",
              offset: 12,
              style: { fill: "var(--text-tertiary)", fontSize: 10 },
            }}
            width={48}
          />
          <Tooltip
            cursor={{
              stroke: "var(--border-default)",
              strokeWidth: 1,
              strokeDasharray: "3 3",
            }}
            content={<ConfidenceTooltip />}
          />
          <Line
            type="monotone"
            dataKey="confidence"
            stroke="var(--iris)"
            strokeWidth={1.5}
            dot={false}
            activeDot={{ r: 3, fill: "var(--iris)" }}
            isAnimationActive={false}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

function ConfidenceTooltip({
  active,
  payload,
}: TooltipProps<number, string>) {
  if (!active || !payload || payload.length === 0) return null;
  const point = payload[0].payload as DataPoint;
  const fullDate = new Date(point.detectedAt).toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
  return (
    <div className="rounded-md border-[0.5px] border-border-default bg-card px-3 py-2">
      <div className="mb-1 font-mono text-[10px] uppercase tracking-wider text-tertiary">
        {point.anomalyId}
      </div>
      <div className="text-[11px] text-secondary">{fullDate}</div>
      <div className="mt-1 flex items-center justify-between gap-4 text-[11px]">
        <span className="text-secondary">Confidence</span>
        <span
          className="font-mono tabular-nums text-iris"
        >
          {(point.confidence * 100).toFixed(1)}%
        </span>
      </div>
    </div>
  );
}
