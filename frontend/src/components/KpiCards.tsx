import { useDrift, useMetricsSummary } from "../hooks/queries";
import { pct } from "../lib/format";

export function KpiCards() {
  const summary = useMetricsSummary();
  const drift = useDrift();

  if (!summary.data) {
    return <KpiSkeleton />;
  }
  const s = summary.data;
  return (
    <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
      <Kpi label="Anomalies (24h)" value={s.total_24h.toLocaleString()} />
      <Kpi
        label="Critical"
        value={s.critical_24h.toLocaleString()}
        accent="text-critical-500"
      />
      <Kpi
        label="Warning"
        value={s.warning_24h.toLocaleString()}
        accent="text-warning-500"
      />
      <Kpi label="Avg confidence" value={pct(s.avg_confidence, 1)} />
      <Kpi
        label="Drift"
        value={drift.data ? drift.data.status.replace("_", " ") : "—"}
        accent={driftAccent(drift.data?.status)}
      />
    </div>
  );
}

function Kpi({
  label,
  value,
  accent,
}: {
  label: string;
  value: string;
  accent?: string;
}) {
  return (
    <div className="rounded-lg border border-slate-800 bg-slate-900/40 p-3">
      <div className="text-xs uppercase tracking-wide text-slate-400">{label}</div>
      <div className={`mt-1 text-2xl font-semibold ${accent ?? "text-slate-100"}`}>
        {value}
      </div>
    </div>
  );
}

function driftAccent(s: string | undefined): string {
  if (s === "drift_critical") return "text-critical-500";
  if (s === "drift_high") return "text-warning-500";
  return "text-emerald-400";
}

function KpiSkeleton() {
  return (
    <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
      {Array.from({ length: 5 }).map((_, i) => (
        <div
          key={i}
          className="h-[68px] animate-pulse rounded-lg border border-slate-800 bg-slate-900/30"
        />
      ))}
    </div>
  );
}
