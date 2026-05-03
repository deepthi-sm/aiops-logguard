import { useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useAnomalies } from "../api/queries";
import {
  AnomalyFilters,
  type AnomalyFiltersState,
  type TimeRange,
} from "../components/AnomalyFilters";
import { AnomalyTable } from "../components/AnomalyTable";
import { EmptyState } from "../components/EmptyState";
import { ErrorState } from "../components/ErrorState";
import { EyebrowLabel } from "../components/EyebrowLabel";
import { Skeleton } from "../components/Skeleton";
import { formatNumber } from "../lib/format";
import type { Anomaly, Origin } from "../types";

const INITIAL_STATE: AnomalyFiltersState = {
  severities: new Set(),
  source: null,
  timeRange: "24h",
  search: "",
  collapseClusters: true,
};

/**
 * /anomalies — filterable, sortable, sticky-header table of every anomaly
 * the system has detected. Per spec: severity chips, source dropdown,
 * time range buttons, free-text search, cluster collapse toggle.
 *
 * The filter logic is client-side on top of an `useAnomalies({ limit: 200 })`
 * fetch. Real production usage would push some of these filters into the
 * server query (the `severity` and `since` params already supported by
 * `/api/v1/anomalies`); for now client-side keeps the UI snappy on the
 * 200-row mock dataset.
 */
export function AnomalyList() {
  const [searchParams] = useSearchParams();
  // After an upload completes, the Upload page redirects here with
  // `?origin=user-upload` — that's a server-side filter so the list
  // only contains anomalies from the just-uploaded file. The legacy
  // `?source=...` URL still works as a UI source-dropdown pre-fill.
  const initialSource = searchParams.get("source");
  const originFilter = (() => {
    const raw = searchParams.get("origin");
    return raw === "user-upload" || raw === "live-stream"
      ? (raw as Origin)
      : null;
  })();
  const [filters, setFilters] = useState<AnomalyFiltersState>({
    ...INITIAL_STATE,
    source: initialSource,
  });
  const list = useAnomalies({
    limit: 200,
    ...(originFilter ? { origin: originFilter } : {}),
  });

  const items = list.data?.items ?? [];

  const sourceOptions = useMemo(
    () => Array.from(new Set(items.map((a) => a.source))).sort(),
    [items],
  );

  const filtered = useMemo(
    () => applyFilters(items, filters),
    [items, filters],
  );

  return (
    <div className="pb-12">
      <Header total={items.length} shown={filtered.length} />
      <AnomalyFilters
        state={filters}
        onChange={setFilters}
        sourceOptions={sourceOptions}
      />

      {list.isLoading && <ListSkeleton />}
      {list.error && (
        <ErrorState
          message={(list.error as Error).message}
          onRetry={() => list.refetch()}
        />
      )}
      {!list.isLoading && !list.error && filtered.length === 0 && (
        <EmptyState
          message={
            items.length === 0
              ? "No anomalies recorded yet."
              : "No anomalies match the current filters."
          }
        />
      )}
      {!list.isLoading && !list.error && filtered.length > 0 && (
        <AnomalyTable
          items={filtered}
          showClusterAffordance={filters.collapseClusters}
        />
      )}
    </div>
  );
}

// -- Header ----------------------------------------------------------------

function Header({ total, shown }: { total: number; shown: number }) {
  return (
    <header className="mb-7 flex items-end justify-between border-b-[0.5px] border-border-subtle pb-5">
      <div>
        <EyebrowLabel>All anomalies</EyebrowLabel>
        <h1 className="text-[22px] font-medium leading-none tracking-[-0.01em] text-primary">
          Anomaly history
        </h1>
      </div>
      <div className="text-[11px] text-tertiary">
        Showing{" "}
        <span className="font-mono text-secondary">{formatNumber(shown)}</span>{" "}
        of {formatNumber(total)}
      </div>
    </header>
  );
}

// -- Filtering -------------------------------------------------------------

function applyFilters(
  items: Anomaly[],
  filters: AnomalyFiltersState,
): Anomaly[] {
  const sinceIso = timeRangeToSince(filters.timeRange);
  const searchLower = filters.search.trim().toLowerCase();

  let result = items;

  if (filters.severities.size > 0) {
    result = result.filter((a) => filters.severities.has(a.severity));
  }
  if (filters.source) {
    result = result.filter((a) => a.source === filters.source);
  }
  if (sinceIso) {
    result = result.filter((a) => a.detected_at >= sinceIso);
  }
  if (searchLower) {
    result = result.filter((a) =>
      a.log_template.toLowerCase().includes(searchLower),
    );
  }
  if (filters.collapseClusters) {
    const seen = new Set<string>();
    result = result.filter((a) => {
      if (seen.has(a.cluster_id)) return false;
      seen.add(a.cluster_id);
      return true;
    });
  }
  return result;
}

function timeRangeToSince(range: TimeRange): string | null {
  if (range === "all") return null;
  const minutesByRange: Record<Exclude<TimeRange, "all">, number> = {
    "1h": 60,
    "24h": 60 * 24,
    "7d": 60 * 24 * 7,
  };
  const minutes = minutesByRange[range];
  return new Date(Date.now() - minutes * 60_000).toISOString();
}

// -- Skeleton --------------------------------------------------------------

function ListSkeleton() {
  return (
    <div className="overflow-hidden rounded-lg border-[0.5px] border-border-subtle bg-card">
      {Array.from({ length: 8 }).map((_, i) => (
        <div
          key={i}
          className="grid grid-cols-[110px_88px_180px_1fr_72px_72px] items-center gap-4 border-b-[0.5px] border-border-subtle px-4 py-3 last:border-b-0"
        >
          <Skeleton className="h-3 w-16 bg-hover" />
          <Skeleton className="h-4 w-16 bg-hover" />
          <Skeleton className="h-3 w-32 bg-hover" />
          <Skeleton className="h-3 w-full bg-hover" />
          <Skeleton className="h-3 w-10 bg-hover justify-self-end" />
          <Skeleton className="h-3 w-10 bg-hover justify-self-end" />
        </div>
      ))}
    </div>
  );
}
