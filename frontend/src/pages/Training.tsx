import { ChevronRight, Terminal } from "lucide-react";
import { useMemo, useState } from "react";
import { useTrainingRuns } from "../api/queries";
import { ErrorState } from "../components/ErrorState";
import { EyebrowLabel } from "../components/EyebrowLabel";
import { Skeleton } from "../components/Skeleton";
import { cn } from "../lib/cn";
import type { TrainingRun, TrainingRunStatus } from "../types";

/**
 * /admin/training — model training run history.
 *
 * Audience: ops engineer monitoring model health in production.
 * Information-dense, calm, scannable. No celebration of metrics.
 *
 * Three sections, top-to-bottom, weighted in the order an ops user
 * actually reads them:
 *
 *   1. Current model (~25%) — compact card. Headline + dataset chip,
 *      a tight 3-tile metric strip (3-decimal precision), supporting
 *      caption with sample size + wall-clock. Hyperparameters and the
 *      raw notes prose live behind a closed `<details>` so they don't
 *      compete for attention.
 *   2. Run history (dominant) — every row in training_runs EXCEPT the
 *      active one (no duplication). Click a row to expand its notes
 *      inline. Status pills + dataset chips so the table reads quickly.
 *   3. Maintenance (thin) — single closed `<details>` with the
 *      retrain bash command. Reference material, demoted from a
 *      full-card section.
 *
 * Source of truth: `GET /api/v1/training/runs` (status derived
 * server-side). This file is pure render — no parsing of "active"
 * happens here, just rendering of what the API said.
 */
export function Training() {
  const { data, isLoading, error, refetch } = useTrainingRuns(50);
  const runs = data?.items ?? [];
  const active = runs.find((r) => r.id === data?.active_id) ?? null;
  const history = runs.filter((r) => r.id !== data?.active_id);

  return (
    <div className="pb-12">
      <header className="mb-7 border-b-[0.5px] border-border-subtle pb-5">
        <EyebrowLabel>Model training</EyebrowLabel>
        <h1 className="text-[22px] font-medium leading-none tracking-[-0.01em] text-primary">
          Training runs
        </h1>
      </header>

      {isLoading && (
        <div className="space-y-3">
          <Skeleton className="h-32 bg-hover" />
          <Skeleton className="h-24 bg-hover" />
        </div>
      )}

      {error && (
        <ErrorState
          message={(error as Error).message}
          onRetry={() => refetch()}
        />
      )}

      {!isLoading && !error && (
        <>
          <CurrentModelSection run={active} />
          <RunHistorySection runs={history} />
          <MaintenanceSection />
        </>
      )}
    </div>
  );
}

// -- Notes parser ----------------------------------------------------------

interface ParsedNotes {
  headline: string;     // "Combined OS+HDFS"
  windows: number | null;  // 261615
  details: string;      // hyperparameters + body, sentences after the headline
}

/**
 * Parse the free-form `notes` column into a headline / windows /
 * details triple. The seed notes follow the pattern
 *
 *   "Model X — <headline-clause> (NNN,NNN windows). <body...>"
 *
 * but the parser tolerates variants — anything that doesn't match the
 * "Model X —" prefix has its first sentence (up to the first period
 * or open-paren) treated as the headline, and the rest as details.
 * The (NNN windows) clause is matched anywhere in the string and
 * surfaced as a separate number; if it doesn't appear we just skip
 * the windows caption.
 */
function parseNotes(notes: string | null | undefined): ParsedNotes {
  if (!notes) return { headline: "", windows: null, details: "" };

  // 1. Strip "Model X — " prefix (em-dash, en-dash, or hyphen).
  const stripped = notes
    .replace(/^Model\s+[A-Z]\s*[—–-]\s*/u, "")
    .trim();

  // 2. Pull the windows count out wherever it appears.
  const wMatch = stripped.match(/\(([\d,]+)\s+windows?\)/i);
  const windows = wMatch
    ? parseInt(wMatch[1].replace(/,/g, ""), 10)
    : null;

  // 3. Headline = everything up to first "." or "(", trimmed.
  const headlineMatch = stripped.match(/^([^.(]+)/);
  const headline = (headlineMatch ? headlineMatch[1] : stripped).trim();

  // 4. Details = everything after the first ". " (the first sentence
  //    boundary). If no period found, no details.
  const firstSentenceEnd = stripped.indexOf(". ");
  const details =
    firstSentenceEnd >= 0
      ? stripped.slice(firstSentenceEnd + 2).trim()
      : "";

  return { headline, windows, details };
}

// -- Time formatters -------------------------------------------------------

function formatTrainingTime(iso: string): string {
  const d = new Date(iso);
  return `${d.toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  })} · ${d.toLocaleTimeString(undefined, {
    hour: "2-digit",
    minute: "2-digit",
    timeZoneName: "short",
  })}`;
}

/** Compute "Nm" or "Hh Mm" from a started/completed pair. */
function formatDuration(
  startedAt: string,
  completedAt: string | null,
): string {
  if (!completedAt) return "in flight";
  const ms = new Date(completedAt).getTime() - new Date(startedAt).getTime();
  if (!Number.isFinite(ms) || ms < 0) return "—";
  const totalMin = Math.round(ms / 60_000);
  if (totalMin < 60) return `${totalMin}m`;
  const h = Math.floor(totalMin / 60);
  const m = totalMin % 60;
  return `${h}h ${m.toString().padStart(2, "0")}m`;
}

// -- Score formatters ------------------------------------------------------

function formatScore3(value: number | null): string {
  return value === null ? "—" : value.toFixed(3);
}

function scoreClass(value: number | null): string {
  if (value === null) return "text-tertiary";
  if (value >= 0.9) return "text-success";
  if (value >= 0.5) return "text-warning";
  return "text-critical";
}

// -- Section 1: current model ----------------------------------------------

function CurrentModelSection({ run }: { run: TrainingRun | null }) {
  if (!run) {
    return (
      <section className="mb-7">
        <h2 className="mb-[10px] text-[11px] uppercase tracking-[0.08em] text-tertiary">
          Current model
        </h2>
        <p className="text-[12px] text-tertiary">
          No run currently qualifies as active. Train and ingest a run
          to populate this section.
        </p>
      </section>
    );
  }

  const parsed = parseNotes(run.notes);
  const duration = formatDuration(run.started_at, run.completed_at);
  const captionParts: string[] = [];
  if (parsed.windows !== null) {
    captionParts.push(`n = ${parsed.windows.toLocaleString()} windows`);
  }
  if (run.completed_at) {
    captionParts.push(`${duration} wall-clock`);
  }
  const caption = captionParts.join(" · ");

  return (
    <section className="mb-7">
      <h2 className="mb-[10px] text-[11px] uppercase tracking-[0.08em] text-tertiary">
        Current model
      </h2>

      <div className="rounded-lg border-[0.5px] border-border-subtle bg-card p-5">
        {/* Top line: status pill + run id + trained timestamp */}
        <div className="flex flex-wrap items-center gap-3">
          <RunStatusPill status={run.status} />
          <span className="font-mono text-[12px] text-secondary">
            run #{run.id}
          </span>
          {run.completed_at && (
            <span className="text-[12px] text-tertiary">
              · trained {formatTrainingTime(run.completed_at)}
            </span>
          )}
        </div>

        {/* Headline + dataset chip */}
        <div className="mt-3 flex flex-wrap items-baseline gap-2">
          <span className="text-[15px] font-medium text-primary">
            {parsed.headline || run.dataset}
          </span>
          {parsed.headline && (
            <DatasetChip dataset={run.dataset} />
          )}
        </div>

        {/* Metric strip — 3 small tiles, 3-decimal precision */}
        <div className="mt-4 grid grid-cols-3 gap-3">
          <MetricTile label="F1" value={run.f1_score} />
          <MetricTile label="Precision" value={run.precision_score} />
          <MetricTile label="Recall" value={run.recall_score} />
        </div>

        {/* Honest supporting context — what gives the three identical
            "1.000"s their meaning. Without this caption, perfect
            scores read as toy data. */}
        {caption && (
          <div className="mt-2 text-[11px] text-tertiary">
            {caption}
            {parsed.headline && (
              <>
                {" · "}
                <span className="font-mono">{run.dataset}</span>
              </>
            )}
          </div>
        )}

        {/* Closed-by-default expander for the developer-y stuff */}
        {(parsed.details || run.artifacts_path) && (
          <details className="group mt-5 border-t-[0.5px] border-border-subtle pt-4">
            <summary className="flex cursor-pointer list-none items-center gap-1.5 text-[11px] uppercase tracking-wider text-tertiary transition-colors hover:text-secondary [&::-webkit-details-marker]:hidden">
              <ChevronRight
                size={11}
                strokeWidth={2}
                className="transition-transform group-open:rotate-90"
              />
              Training config
            </summary>
            <div className="mt-3 space-y-3 rounded-md border-[0.5px] border-border-subtle bg-page p-4">
              <ConfigRow
                label="Started"
                value={formatTrainingTime(run.started_at)}
              />
              {run.completed_at && (
                <ConfigRow
                  label="Completed"
                  value={formatTrainingTime(run.completed_at)}
                />
              )}
              <ConfigRow label="Duration" value={duration} />
              {run.artifacts_path && (
                <ConfigRow
                  label="Artifacts"
                  value={run.artifacts_path}
                  mono
                />
              )}
              {parsed.details && (
                <div className="border-t-[0.5px] border-border-subtle pt-3">
                  <div className="mb-1.5 text-[10px] uppercase tracking-wider text-tertiary">
                    Notes
                  </div>
                  <p className="text-[12px] leading-relaxed text-secondary">
                    {parsed.details}
                  </p>
                </div>
              )}
            </div>
          </details>
        )}
      </div>
    </section>
  );
}

function MetricTile({
  label,
  value,
}: {
  label: string;
  value: number | null;
}) {
  return (
    <div className="rounded-md border-[0.5px] border-border-subtle bg-page px-3 py-2.5">
      <div className="text-[10px] uppercase tracking-wider text-tertiary">
        {label}
      </div>
      <div
        className={cn(
          "mt-1 font-mono text-[18px] tabular-nums",
          scoreClass(value),
        )}
      >
        {formatScore3(value)}
      </div>
    </div>
  );
}

function ConfigRow({
  label,
  value,
  mono,
}: {
  label: string;
  value: string;
  mono?: boolean;
}) {
  return (
    <div className="flex items-baseline gap-3 text-[12px]">
      <span className="w-[88px] shrink-0 text-[10px] uppercase tracking-wider text-tertiary">
        {label}
      </span>
      <span
        className={cn(
          "min-w-0 flex-1 break-all text-secondary",
          mono && "font-mono text-[12px]",
        )}
      >
        {value}
      </span>
    </div>
  );
}

// -- Section 2: run history ------------------------------------------------

function RunHistorySection({ runs }: { runs: TrainingRun[] }) {
  const [expandedId, setExpandedId] = useState<number | null>(null);

  return (
    <section className="mb-7">
      <h2 className="mb-[10px] text-[11px] uppercase tracking-[0.08em] text-tertiary">
        Run history
      </h2>

      {runs.length === 0 ? (
        <p className="text-[12px] text-tertiary">
          No previous runs.
        </p>
      ) : (
        <div className="overflow-hidden rounded-lg border-[0.5px] border-border-subtle bg-card">
          {/* Header row — same grid template as data rows */}
          <div className="grid grid-cols-[180px_88px_1fr_72px_72px_72px_84px_18px] items-center gap-3 border-b-[0.5px] border-border-subtle px-4 py-2.5 text-[10px] uppercase tracking-wider text-tertiary">
            <div>Trained</div>
            <div>Status</div>
            <div>Dataset</div>
            <div className="text-right">F1</div>
            <div className="text-right">P</div>
            <div className="text-right">R</div>
            <div className="text-right">Duration</div>
            <div></div>
          </div>
          <div className="divide-y-[0.5px] divide-border-subtle">
            {runs.map((r) => (
              <RunHistoryRow
                key={r.id}
                run={r}
                expanded={expandedId === r.id}
                onToggle={() =>
                  setExpandedId(expandedId === r.id ? null : r.id)
                }
              />
            ))}
          </div>
        </div>
      )}
    </section>
  );
}

function RunHistoryRow({
  run,
  expanded,
  onToggle,
}: {
  run: TrainingRun;
  expanded: boolean;
  onToggle: () => void;
}) {
  const parsed = parseNotes(run.notes);
  const duration = formatDuration(run.started_at, run.completed_at);

  return (
    <div>
      <button
        type="button"
        onClick={onToggle}
        className="grid w-full grid-cols-[180px_88px_1fr_72px_72px_72px_84px_18px] items-center gap-3 px-4 py-3 text-left transition-colors hover:bg-hover"
      >
        <div className="text-[12px] text-secondary">
          {run.completed_at
            ? formatTrainingTime(run.completed_at)
            : "in flight"}
        </div>
        <div>
          <RunStatusPill status={run.status} />
        </div>
        <div className="min-w-0 truncate">
          <DatasetChip dataset={run.dataset} />
        </div>
        <div
          className={cn(
            "text-right font-mono text-[12px] tabular-nums",
            scoreClass(run.f1_score),
          )}
        >
          {formatScore3(run.f1_score)}
        </div>
        <div
          className={cn(
            "text-right font-mono text-[12px] tabular-nums",
            scoreClass(run.precision_score),
          )}
        >
          {formatScore3(run.precision_score)}
        </div>
        <div
          className={cn(
            "text-right font-mono text-[12px] tabular-nums",
            scoreClass(run.recall_score),
          )}
        >
          {formatScore3(run.recall_score)}
        </div>
        <div className="text-right font-mono text-[12px] tabular-nums text-tertiary">
          {duration}
        </div>
        <div className="flex justify-end text-tertiary">
          <ChevronRight
            size={12}
            strokeWidth={2}
            className={cn(
              "transition-transform",
              expanded && "rotate-90",
            )}
          />
        </div>
      </button>
      {expanded && (
        <div className="border-t-[0.5px] border-border-subtle bg-page px-4 py-4 text-[12px] leading-relaxed text-secondary">
          {parsed.headline && (
            <div className="mb-1 font-medium text-primary">
              {parsed.headline}
              {parsed.windows !== null && (
                <span className="ml-2 font-mono text-[11px] text-tertiary">
                  n = {parsed.windows.toLocaleString()} windows
                </span>
              )}
            </div>
          )}
          {parsed.details && <p>{parsed.details}</p>}
          {run.artifacts_path && (
            <div className="mt-2 font-mono text-[11px] text-tertiary">
              Artifacts: {run.artifacts_path}
            </div>
          )}
          {!parsed.headline && !parsed.details && !run.artifacts_path && (
            <span className="text-tertiary">
              No additional notes recorded for this run.
            </span>
          )}
        </div>
      )}
    </div>
  );
}

// -- Section 3: maintenance ------------------------------------------------

function MaintenanceSection() {
  return (
    <section>
      <h2 className="mb-[10px] text-[11px] uppercase tracking-[0.08em] text-tertiary">
        Maintenance
      </h2>
      <div className="rounded-lg border-[0.5px] border-border-subtle bg-card">
        <details className="group">
          <summary className="flex cursor-pointer list-none items-center gap-2 px-5 py-3 text-[12px] text-secondary transition-colors hover:bg-hover [&::-webkit-details-marker]:hidden">
            <ChevronRight
              size={12}
              strokeWidth={2}
              className="text-tertiary transition-transform group-open:rotate-90"
            />
            <Terminal
              size={12}
              strokeWidth={1.5}
              className="text-tertiary"
            />
            <span>Developer: retrain command</span>
          </summary>
          <div className="border-t-[0.5px] border-border-subtle px-5 py-4">
            <p className="text-[12px] leading-relaxed text-secondary">
              Models are persisted to{" "}
              <code className="font-mono text-primary">
                backend/artifacts/
              </code>
              . To retrain on a different dataset, run from the backend
              project root:
            </p>
            <pre className="mt-3 overflow-x-auto rounded-md border-[0.5px] border-border-subtle bg-page px-3 py-2.5 font-mono text-[12px] leading-relaxed text-primary">
              <code>{`cd backend
python -m training.run_full_pipeline --dataset bgl`}</code>
            </pre>
            <p className="mt-3 text-[11px] leading-relaxed text-tertiary">
              The run overwrites{" "}
              <code className="font-mono">transformer.pt</code>,{" "}
              <code className="font-mono">autoencoder.pt</code>,{" "}
              <code className="font-mono">confidence_scorer.pt</code>{" "}
              and{" "}
              <code className="font-mono">thresholds.json</code> in the
              artifact volume, then inserts a new row into{" "}
              <code className="font-mono">training_runs</code>. Restart
              the Runner and RAG worker afterwards so they pick up the
              new artifacts.
            </p>
          </div>
        </details>
      </div>
    </section>
  );
}

// -- Shared chips / pills --------------------------------------------------

function DatasetChip({ dataset }: { dataset: string }) {
  return (
    <span className="rounded-md border-[0.5px] border-border-subtle bg-page px-1.5 py-0.5 font-mono text-[11px] text-tertiary">
      {dataset}
    </span>
  );
}

function RunStatusPill({ status }: { status: TrainingRunStatus }) {
  if (status === "active") {
    return (
      <span className="inline-flex items-center rounded-md border-[0.5px] border-success/40 bg-success/10 px-2 py-0.5 text-[10px] uppercase tracking-wider text-success">
        active
      </span>
    );
  }
  if (status === "failed") {
    return (
      <span className="inline-flex items-center rounded-md border-[0.5px] border-critical/40 bg-critical/10 px-2 py-0.5 text-[10px] uppercase tracking-wider text-critical">
        failed
      </span>
    );
  }
  return (
    <span className="inline-flex items-center rounded-md border-[0.5px] border-border-subtle bg-page px-2 py-0.5 text-[10px] uppercase tracking-wider text-tertiary">
      done
    </span>
  );
}
