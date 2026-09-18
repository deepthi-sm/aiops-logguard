import { Search } from "lucide-react";
import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useFeedbackHistory } from "../api/queries";
import { EyebrowLabel } from "../components/EyebrowLabel";
import { ErrorState } from "../components/ErrorState";
import { Skeleton } from "../components/Skeleton";
import { cn } from "../lib/cn";
import { formatRelativeTime } from "../lib/format";
import type { FeedbackHistoryItem } from "../types";

/**
 * /admin/incidents — confirmed-incident knowledge base.
 *
 * Source of truth: anomalies marked verdict="true_positive" via the
 * Feedback page. The list comes from the existing
 * `GET /api/v1/feedback` endpoint (newest first, capped at 200), then
 * filtered client-side to true_positive — that endpoint already returns
 * everything we need (anomaly_id, source, severity, log_template,
 * submitted_at, root_cause), so no extra fetch per row.
 *
 * Layout (per the approved Phase-1 wireframe):
 *
 *   ┌──────────────────────────────────────────────────────────────┐
 *   │  CONFIRMED INCIDENTS                                         │
 *   │  True-positive history                                       │
 *   │  18 anomalies confirmed by engineer feedback as real        │
 *   │  ─────────────────────────────────────────────────────       │
 *   │                                                              │
 *   │  [🔍 Search…]   [All] [bgl-2k] [thunderbird] [mixed]         │
 *   │                                                              │
 *   │  ┌──────────────────────────────────────────────────────┐    │
 *   │  │ ✓ anom_…2919   bgl-2k     CRITICAL    2 min ago      │    │
 *   │  │   FATAL R02-… RAS KERNEL FATAL data TLB error        │    │
 *   │  │   ROOT CAUSE: A data-storage interrupt fired …       │    │
 *   │  │                              [open anomaly →]        │    │
 *   │  └──────────────────────────────────────────────────────┘    │
 *   └──────────────────────────────────────────────────────────────┘
 *
 * Filters:
 *   - Search: substring match against anomaly_id, log_template,
 *     root_cause, source.
 *   - Source chips: every distinct `source` value across the list,
 *     sorted alphabetically. "All" clears the filter.
 *
 * Empty / loading / error states reuse Skeleton + ErrorState +
 * inline-message patterns the rest of the app already uses.
 */
export function Incidents() {
  // 200-row cap matches the Feedback page; if a deployment ever needs
  // more we can add pagination, but in practice human-confirmed
  // incidents grow slowly enough that 200 is plenty.
  const { data, isLoading, error, refetch } = useFeedbackHistory(200);

  // Filter to verdict='true_positive' — these are the rows the user
  // has explicitly marked as real incidents. The Feedback page lists
  // both verdicts (for review); the Incidents page is the curated
  // subset.
  const truePositives = useMemo(
    () =>
      (data?.items ?? []).filter(
        (i) => i.verdict === "true_positive",
      ),
    [data],
  );

  const [query, setQuery] = useState("");
  const [source, setSource] = useState<string | null>(null);

  // Build the source-filter chip list from whatever sources actually
  // appear in the user's confirmed-incident set, not a hardcoded list.
  const sources = useMemo(
    () =>
      Array.from(new Set(truePositives.map((i) => i.source))).sort(),
    [truePositives],
  );

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return truePositives.filter((i) => {
      if (source && i.source !== source) return false;
      if (!q) return true;
      return (
        i.anomaly_id.toLowerCase().includes(q) ||
        i.log_template.toLowerCase().includes(q) ||
        (i.root_cause ?? "").toLowerCase().includes(q) ||
        i.source.toLowerCase().includes(q)
      );
    });
  }, [truePositives, query, source]);

  return (
    <div className="pb-12">
      <header className="mb-7 border-b-[0.5px] border-border-subtle pb-5">
        <EyebrowLabel>Confirmed incidents</EyebrowLabel>
        <h1 className="text-[22px] font-medium leading-none tracking-[-0.01em] text-primary">
          True-positive history
        </h1>
        <p className="mt-2 text-[12px] text-tertiary">
          {isLoading ? (
            "Loading…"
          ) : (
            <>
              <span className="font-mono">{truePositives.length}</span>{" "}
              {truePositives.length === 1 ? "anomaly" : "anomalies"}{" "}
              confirmed by engineer feedback as real incidents.
            </>
          )}
        </p>
      </header>

      {/* Search + source filters */}
      {!isLoading && truePositives.length > 0 && (
        <div className="mb-4 flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
          <div className="relative md:w-80">
            <Search
              size={12}
              strokeWidth={1.5}
              className="absolute left-3 top-1/2 -translate-y-1/2 text-tertiary"
            />
            <input
              type="search"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search incidents…"
              className="w-full rounded-md border-[0.5px] border-border-subtle bg-card py-1.5 pl-8 pr-3 text-[12px] text-primary placeholder:text-tertiary focus:border-iris/40 focus:outline-none"
            />
          </div>
          {sources.length > 1 && (
            <div className="flex flex-wrap items-center gap-2">
              <SourceChip
                active={source === null}
                onClick={() => setSource(null)}
              >
                All
              </SourceChip>
              {sources.map((s) => (
                <SourceChip
                  key={s}
                  active={source === s}
                  onClick={() => setSource(s)}
                >
                  {s}
                </SourceChip>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Body — loading / error / empty / list */}
      {isLoading && (
        <div className="space-y-3">
          <Skeleton className="h-20 bg-hover" />
          <Skeleton className="h-20 bg-hover" />
          <Skeleton className="h-20 bg-hover" />
        </div>
      )}

      {error && (
        <ErrorState
          message={(error as Error).message}
          onRetry={() => refetch()}
        />
      )}

      {!isLoading && !error && truePositives.length === 0 && (
        <div className="rounded-lg border-[0.5px] border-border-subtle bg-card px-5 py-10 text-center text-[12px] text-tertiary">
          No confirmed incidents yet. Mark anomalies as{" "}
          <span className="font-mono text-primary">true positive</span> on
          the Feedback page to populate this list.
        </div>
      )}

      {!isLoading && !error && truePositives.length > 0 && filtered.length === 0 && (
        <div className="rounded-lg border-[0.5px] border-border-subtle bg-card px-5 py-10 text-center text-[12px] text-tertiary">
          No incidents match this filter.
        </div>
      )}

      {!isLoading && !error && filtered.length > 0 && (
        <div className="overflow-hidden rounded-lg border-[0.5px] border-border-subtle bg-card">
          <div className="divide-y-[0.5px] divide-border-subtle">
            {filtered.map((i) => (
              <IncidentRow key={i.anomaly_id} item={i} />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

// -- Sub-components --------------------------------------------------------

function IncidentRow({ item }: { item: FeedbackHistoryItem }) {
  // Strip the "ROOT CAUSE: " / "IMPACT: " labels from the root_cause
  // field (the parser stores them inline) so the snippet reads as
  // prose rather than a structured dump. Truncated to ~180 chars
  // because the full postmortem lives one click away.
  const rawSnippet = (item.root_cause ?? "").trim();
  const cleanSnippet = rawSnippet
    .replace(/^ROOT CAUSE:\s*/i, "")
    .split(/\n\nIMPACT:/i)[0]
    .trim();
  const snippet =
    cleanSnippet.length > 180
      ? cleanSnippet.slice(0, 180).trimEnd() + "…"
      : cleanSnippet;

  return (
    <Link
      to={`/anomalies/${encodeURIComponent(item.anomaly_id)}`}
      className="block px-4 py-3 transition-colors hover:bg-hover"
    >
      <div className="flex items-baseline justify-between gap-4">
        <div className="flex items-center gap-3">
          {/* Faint-bg + bordered pill — the solid bg-critical helper
              made the text invisible because text-critical is the
              same coral. Use the faint /10 pattern that the rest of
              the dashboard uses for severity pills. */}
          <span
            className={cn(
              "rounded-md border-[0.5px] px-1.5 py-0.5 text-[10px] uppercase tracking-wider",
              item.severity === "critical" &&
                "border-critical/40 bg-critical/10 text-critical",
              item.severity === "warning" &&
                "border-warning/40 bg-warning/10 text-warning",
              item.severity === "info" &&
                "border-info/40 bg-info/10 text-info",
            )}
          >
            {item.severity}
          </span>
          <span className="font-mono text-[12px] text-iris">
            {item.anomaly_id}
          </span>
          <span className="rounded-md border-[0.5px] border-border-subtle bg-page px-1.5 py-0.5 text-[11px] text-tertiary">
            {item.source}
          </span>
        </div>
        <span
          className="text-[11px] text-tertiary"
          title={new Date(item.submitted_at).toLocaleString()}
        >
          {formatRelativeTime(item.submitted_at)}
        </span>
      </div>
      <div className="mt-1.5 truncate font-mono text-[12px] text-primary">
        {item.log_template || "(no template)"}
      </div>
      {snippet && (
        <div className="mt-1.5 line-clamp-2 text-[12px] leading-relaxed text-secondary">
          {snippet}
        </div>
      )}
    </Link>
  );
}

function SourceChip({
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
        "rounded-md border-[0.5px] px-2.5 py-1 text-[11px] transition-colors",
        active
          ? "border-iris/40 bg-iris/10 text-iris"
          : "border-border-subtle bg-card text-secondary hover:bg-hover hover:text-primary",
      )}
    >
      {children}
    </button>
  );
}
