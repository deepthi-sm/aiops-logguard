import { useAnomalies } from "../hooks/queries";
import type { Anomaly, Severity } from "../api/types";
import { classes, pct, timeAgo } from "../lib/format";
import { SeverityBadge } from "./SeverityBadge";
import { useState } from "react";

interface Props {
  selectedId: string | null;
  onSelect: (id: string) => void;
}

export function AnomalyList({ selectedId, onSelect }: Props) {
  const [filter, setFilter] = useState<Severity | "all">("all");
  const list = useAnomalies({
    limit: 50,
    severity: filter === "all" ? undefined : filter,
  });

  return (
    <div className="flex h-full flex-col rounded-lg border border-slate-800 bg-slate-900/40">
      <div className="flex items-center justify-between border-b border-slate-800 px-4 py-2.5">
        <h2 className="text-sm font-semibold">Live anomalies</h2>
        <FilterTabs value={filter} onChange={setFilter} />
      </div>
      <div className="flex-1 overflow-y-auto">
        {list.isLoading && (
          <div className="p-4 text-sm text-slate-400">Loading…</div>
        )}
        {list.error && (
          <div className="p-4 text-sm text-critical-500">
            {(list.error as Error).message}
          </div>
        )}
        {list.data?.items.length === 0 && (
          <div className="p-4 text-sm text-slate-400">No anomalies yet.</div>
        )}
        <ul className="divide-y divide-slate-800">
          {list.data?.items.map((a) => (
            <Row
              key={a.id}
              a={a}
              selected={a.id === selectedId}
              onClick={() => onSelect(a.id)}
            />
          ))}
        </ul>
      </div>
    </div>
  );
}

function Row({
  a,
  selected,
  onClick,
}: {
  a: Anomaly;
  selected: boolean;
  onClick: () => void;
}) {
  return (
    <li>
      <button
        onClick={onClick}
        className={classes(
          "flex w-full flex-col gap-1 px-4 py-3 text-left transition-colors",
          selected
            ? "bg-slate-800/60"
            : "hover:bg-slate-800/30",
        )}
      >
        <div className="flex items-center gap-2">
          <SeverityBadge severity={a.severity} />
          <span className="font-mono text-xs text-slate-400">{a.source}</span>
          <span className="ml-auto text-xs text-slate-500">
            {timeAgo(a.detected_at)}
          </span>
        </div>
        <div className="truncate font-mono text-xs text-slate-300">
          {a.log_template}
        </div>
        <div className="flex items-center gap-3 text-[11px] text-slate-500">
          <span>score {pct(a.ensemble_score, 0)}</span>
          <span>conf {pct(a.confidence, 0)}</span>
          {a.cluster_size > 1 && (
            <span className="rounded bg-slate-800 px-1.5 py-0.5 text-slate-400">
              ×{a.cluster_size}
            </span>
          )}
        </div>
      </button>
    </li>
  );
}

function FilterTabs({
  value,
  onChange,
}: {
  value: Severity | "all";
  onChange: (v: Severity | "all") => void;
}) {
  const opts: (Severity | "all")[] = ["all", "critical", "warning", "info"];
  return (
    <div className="flex gap-1 rounded-md border border-slate-800 bg-slate-900/60 p-0.5">
      {opts.map((o) => (
        <button
          key={o}
          onClick={() => onChange(o)}
          className={classes(
            "rounded px-2 py-0.5 text-[11px] capitalize",
            value === o ? "bg-slate-700 text-slate-100" : "text-slate-400 hover:text-slate-200",
          )}
        >
          {o}
        </button>
      ))}
    </div>
  );
}
