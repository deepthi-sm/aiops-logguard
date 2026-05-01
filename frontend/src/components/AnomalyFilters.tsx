import { Search } from "lucide-react";
import { cn } from "../lib/cn";
import type { Severity } from "../types";

export type TimeRange = "1h" | "24h" | "7d" | "all";

const SEVERITIES: Severity[] = ["critical", "warning", "info"];
const TIME_RANGES: { value: TimeRange; label: string }[] = [
  { value: "1h", label: "Last hour" },
  { value: "24h", label: "Last 24h" },
  { value: "7d", label: "Last 7d" },
  { value: "all", label: "All time" },
];

export interface AnomalyFiltersState {
  severities: Set<Severity>;
  source: string | null;
  timeRange: TimeRange;
  search: string;
  collapseClusters: boolean;
}

interface AnomalyFiltersProps {
  state: AnomalyFiltersState;
  onChange: (next: AnomalyFiltersState) => void;
  sourceOptions: string[];
}

/**
 * Filter bar above the anomaly table.
 *
 * Per spec:
 *   - Severity multi-select (chips)
 *   - Source dropdown (deduped from results)
 *   - Time range buttons (last hour / 24h / 7d / all)
 *   - Search input on log_template substring
 *   - Cluster collapse toggle (default ON)
 */
export function AnomalyFilters({
  state,
  onChange,
  sourceOptions,
}: AnomalyFiltersProps) {
  const toggleSeverity = (s: Severity) => {
    const next = new Set(state.severities);
    if (next.has(s)) next.delete(s);
    else next.add(s);
    onChange({ ...state, severities: next });
  };

  return (
    <div className="mb-7 space-y-3">
      {/* Row 1: severity chips + time range + cluster toggle */}
      <div className="flex flex-wrap items-center gap-3">
        <div className="flex gap-1">
          {SEVERITIES.map((s) => (
            <SeverityChip
              key={s}
              severity={s}
              active={state.severities.has(s)}
              onClick={() => toggleSeverity(s)}
            />
          ))}
        </div>

        <div className="ml-2 h-5 w-px bg-border-subtle" aria-hidden />

        <div className="flex gap-1 rounded-md border-[0.5px] border-border-subtle bg-card p-0.5">
          {TIME_RANGES.map((r) => (
            <button
              key={r.value}
              type="button"
              onClick={() => onChange({ ...state, timeRange: r.value })}
              className={cn(
                "rounded px-2 py-0.5 text-[11px] transition-colors",
                state.timeRange === r.value
                  ? "bg-hover text-primary"
                  : "text-tertiary hover:text-secondary",
              )}
            >
              {r.label}
            </button>
          ))}
        </div>

        <label className="ml-auto flex items-center gap-2 text-[11px] text-tertiary">
          <input
            type="checkbox"
            checked={state.collapseClusters}
            onChange={(e) =>
              onChange({ ...state, collapseClusters: e.target.checked })
            }
            className="h-3 w-3 rounded-sm border-[0.5px] border-border-default bg-card text-iris"
          />
          Collapse clusters
        </label>
      </div>

      {/* Row 2: search + source dropdown */}
      <div className="flex items-center gap-3">
        <div className="relative flex-1 max-w-md">
          <Search
            size={12}
            strokeWidth={1.5}
            className="absolute left-3 top-1/2 -translate-y-1/2 text-tertiary"
          />
          <input
            type="text"
            value={state.search}
            onChange={(e) => onChange({ ...state, search: e.target.value })}
            placeholder="Filter by template substring…"
            className="w-full rounded-md border-[0.5px] border-border-subtle bg-card py-1.5 pl-8 pr-3 text-[12px] text-primary placeholder:text-tertiary focus:border-iris/50 focus:outline-none"
          />
        </div>

        <select
          value={state.source ?? ""}
          onChange={(e) =>
            onChange({ ...state, source: e.target.value || null })
          }
          className="rounded-md border-[0.5px] border-border-subtle bg-card px-3 py-1.5 text-[12px] text-primary focus:border-iris/50 focus:outline-none"
        >
          <option value="">All sources</option>
          {sourceOptions.map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>
      </div>
    </div>
  );
}

function SeverityChip({
  severity,
  active,
  onClick,
}: {
  severity: Severity;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "rounded-md border-[0.5px] px-2.5 py-1 text-[11px] font-medium uppercase tracking-wider transition-colors",
        active
          ? severity === "critical"
            ? "border-critical/40 bg-critical/10 text-critical"
            : severity === "warning"
              ? "border-warning/40 bg-warning/10 text-warning"
              : "border-info/40 bg-info/10 text-info"
          : "border-border-subtle text-tertiary hover:text-secondary",
      )}
    >
      {severity}
    </button>
  );
}
