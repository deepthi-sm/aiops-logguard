import { Search } from "lucide-react";
import { useMemo, useState } from "react";
import { EyebrowLabel } from "../components/EyebrowLabel";
import { cn } from "../lib/cn";

/**
 * /incidents — the FAISS-indexed knowledge base browser.
 *
 *   ┌────────────────────────────────────────────────────────────┐
 *   │  Incident knowledge base                                   │
 *   │  Indexed incidents                                         │
 *   │  20 incidents indexed in FAISS · used by RAG               │
 *   │  ───────────────────────────────────────────────────────   │
 *   │  [🔍 Search templates…]                  [All] [Tag:auth]  │
 *   │                                                            │
 *   │  syn_001  ERROR connection refused …    auth   2025-12-01  │
 *   │  syn_002  ERROR OOMKilled container …   ops    2025-11-03  │
 *   │  …                                                         │
 *   └────────────────────────────────────────────────────────────┘
 *
 * The 20 seed incidents come from the user's `training/RESULTS.md` and
 * the RAG seed file (`backend/rag/incidents.jsonl`). When the FAISS
 * index becomes browsable via an API, swap the inline list for
 * `useIncidents()`.
 */

interface IndexedIncident {
  id: string;
  template: string;
  resolved_at: string;
  tag: string;
  description: string;
}

const INCIDENTS: IndexedIncident[] = [
  {
    id: "syn_001",
    template: "ERROR connection refused upstream <*>",
    resolved_at: "2025-12-01T14:30:00Z",
    tag: "network",
    description: "Upstream service refused new TCP connections.",
  },
  {
    id: "syn_002",
    template: "ERROR OOMKilled container terminated <*>",
    resolved_at: "2025-11-03T22:00:00Z",
    tag: "ops",
    description: "Container exceeded its cgroup memory limit.",
  },
  {
    id: "syn_003",
    template: "ERROR disk space exhausted on <*> usage <*>%",
    resolved_at: "2025-10-19T11:14:00Z",
    tag: "ops",
    description: "Filesystem ran out of inodes / blocks.",
  },
  {
    id: "syn_004",
    template: "ERROR connection timed out upstream <*>",
    resolved_at: "2025-10-12T18:22:00Z",
    tag: "network",
    description: "Upstream stopped responding within client timeout.",
  },
  {
    id: "syn_005",
    template: "ERROR database connection pool exhausted <*>",
    resolved_at: "2025-09-30T09:48:00Z",
    tag: "db",
    description: "Pool size hit max; new requests blocked.",
  },
  {
    id: "syn_006",
    template: "ERROR ssl handshake failed cert expired <*>",
    resolved_at: "2025-09-12T07:33:00Z",
    tag: "security",
    description: "TLS certificate had expired.",
  },
  {
    id: "syn_007",
    template: "ERROR authentication failed user <*> ip <*>",
    resolved_at: "2025-12-14T08:32:00Z",
    tag: "auth",
    description: "Concentrated brute-force or credential-stuffing attempt.",
  },
  {
    id: "syn_008",
    template: "WARN slow query took <*> ms threshold <*>",
    resolved_at: "2025-12-08T09:14:00Z",
    tag: "db",
    description: "Query exceeded slow-query threshold.",
  },
  {
    id: "syn_009",
    template: "ERROR kubernetes pod crashloopbackoff <*>",
    resolved_at: "2025-08-21T16:05:00Z",
    tag: "ops",
    description: "Pod failed liveness check repeatedly and restarted.",
  },
  {
    id: "syn_010",
    template: "WARN latency spike service <*> p99 <*>",
    resolved_at: "2025-12-23T19:51:00Z",
    tag: "perf",
    description: "Tail latency rose past SLO.",
  },
  {
    id: "syn_011",
    template: "WARN cache stampede repeated misses key <*>",
    resolved_at: "2025-11-18T10:08:00Z",
    tag: "perf",
    description: "Many concurrent fills for a single hot key.",
  },
  {
    id: "syn_012",
    template: "WARN rate limit exceeded client <*> limit <*>",
    resolved_at: "2025-09-02T16:40:00Z",
    tag: "auth",
    description: "Single client tripped the per-second rate limit.",
  },
  {
    id: "syn_013",
    template: "ERROR redis connection refused <*>",
    resolved_at: "2025-08-09T11:00:00Z",
    tag: "db",
    description: "Redis unavailable; clients failed open or closed.",
  },
  {
    id: "syn_014",
    template: "ERROR kafka broker not available <*>",
    resolved_at: "2025-07-15T13:10:00Z",
    tag: "ops",
    description: "Broker partition unreachable; producers buffered.",
  },
  {
    id: "syn_015",
    template: "WARN gc pause exceeded <*> ms heap <*>",
    resolved_at: "2026-02-03T05:20:00Z",
    tag: "perf",
    description: "Long GC pause blocked the request thread.",
  },
  {
    id: "syn_016",
    template: "ERROR healthcheck failed response code <*> path <*>",
    resolved_at: "2026-02-09T07:40:00Z",
    tag: "ops",
    description: "Liveness/readiness probe returned non-200.",
  },
  {
    id: "syn_017",
    template: "WARN memory leak detected rss growth <*> mb per hour",
    resolved_at: "2025-08-09T11:00:00Z",
    tag: "perf",
    description: "Sustained memory growth without traffic correlation.",
  },
  {
    id: "syn_018",
    template: "ERROR deadlock detected transaction <*>",
    resolved_at: "2025-12-29T14:55:00Z",
    tag: "db",
    description: "Two transactions waited on each other's locks.",
  },
  {
    id: "syn_019",
    template: "ERROR upstream 5xx burst service <*> count <*>",
    resolved_at: "2026-01-15T14:32:00Z",
    tag: "network",
    description: "Downstream returned 5xx at elevated rate.",
  },
  {
    id: "syn_020",
    template: "WARN replication lag <*>s threshold <*>s",
    resolved_at: "2026-03-04T20:18:00Z",
    tag: "db",
    description: "Replica fell behind primary beyond threshold.",
  },
];

const TAGS = Array.from(new Set(INCIDENTS.map((i) => i.tag))).sort();

export function Incidents() {
  const [query, setQuery] = useState("");
  const [tag, setTag] = useState<string | null>(null);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return INCIDENTS.filter((i) => {
      if (tag && i.tag !== tag) return false;
      if (!q) return true;
      return (
        i.template.toLowerCase().includes(q) ||
        i.description.toLowerCase().includes(q) ||
        i.id.toLowerCase().includes(q)
      );
    });
  }, [query, tag]);

  return (
    <div className="pb-12">
      <header className="mb-7 border-b-[0.5px] border-border-subtle pb-5">
        <EyebrowLabel>Incident knowledge base</EyebrowLabel>
        <h1 className="text-[22px] font-medium leading-none tracking-[-0.01em] text-primary">
          Indexed incidents
        </h1>
        <p className="mt-2 text-[12px] text-tertiary">
          <span className="font-mono">{INCIDENTS.length}</span> incidents
          indexed in FAISS · referenced by the RAG worker for root-cause
          retrieval.
        </p>
      </header>

      {/* Search + tag filters */}
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
            placeholder="Search templates…"
            className="w-full rounded-md border-[0.5px] border-border-subtle bg-card py-1.5 pl-8 pr-3 text-[12px] text-primary placeholder:text-tertiary focus:border-iris/40 focus:outline-none"
          />
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <TagChip active={tag === null} onClick={() => setTag(null)}>
            All
          </TagChip>
          {TAGS.map((t) => (
            <TagChip key={t} active={tag === t} onClick={() => setTag(t)}>
              {t}
            </TagChip>
          ))}
        </div>
      </div>

      {/* List */}
      <div className="overflow-hidden rounded-lg border-[0.5px] border-border-subtle bg-card">
        {filtered.length === 0 && (
          <div className="px-5 py-8 text-center text-[12px] text-tertiary">
            No incidents match this filter.
          </div>
        )}
        <div className="divide-y-[0.5px] divide-border-subtle">
          {filtered.map((i) => (
            <div key={i.id} className="px-4 py-3">
              <div className="flex items-baseline justify-between gap-4">
                <span className="font-mono text-[12px] text-iris">{i.id}</span>
                <span
                  className="text-[11px] text-tertiary"
                  title={new Date(i.resolved_at).toLocaleString()}
                >
                  resolved{" "}
                  {new Date(i.resolved_at).toLocaleDateString(undefined, {
                    year: "numeric",
                    month: "short",
                    day: "numeric",
                  })}
                </span>
              </div>
              <div className="mt-1 font-mono text-[12px] text-primary">
                {i.template}
              </div>
              <div className="mt-1.5 flex items-center gap-2 text-[11px]">
                <span className="rounded-md border-[0.5px] border-border-subtle bg-page px-1.5 py-0.5 text-tertiary">
                  {i.tag}
                </span>
                <span className="text-tertiary">{i.description}</span>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function TagChip({
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
