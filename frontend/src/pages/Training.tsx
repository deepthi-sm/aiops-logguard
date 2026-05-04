import {
  CheckCircle2,
  Database,
  GitBranch,
  Terminal,
  XCircle,
} from "lucide-react";
import { useTrainingRuns } from "../api/queries";
import { ErrorState } from "../components/ErrorState";
import { EyebrowLabel } from "../components/EyebrowLabel";
import { Skeleton } from "../components/Skeleton";
import { cn } from "../lib/cn";
import type { TrainingRun } from "../types";

/**
 * /admin/training — model training run history.
 *
 * Source of truth: the `training_runs` Postgres table, exposed via
 * `GET /api/v1/training/runs`. The API derives the per-row `status`
 * field server-side ("active" / "completed" / "failed") so this page
 * is pure render.
 *
 * Layout:
 *   1. Active run card — the run currently loaded in the live
 *      detector (most recent completed run with f1 >= 0.5). Falls
 *      back to a friendly empty state when no run qualifies.
 *   2. "How to retrain" instruction box with the documented bash
 *      command. Per the spec we don't surface a "trigger retrain"
 *      button — running the pipeline touches GPU and rewrites the
 *      artifact volume; safer to keep that an explicit operator
 *      action.
 *   3. Run history table — every row in training_runs, newest first.
 *
 * Persistence model is unchanged: each `run_full_pipeline.py`
 * invocation overwrites `backend/artifacts/{transformer,autoencoder,
 * confidence_scorer}.pt` along with `thresholds.json`. The artifacts
 * dir is a Docker volume; "previous runs" here come from the DB
 * table (auto-seeded on API boot, then appended to by CI / manual
 * inserts).
 */
export function Training() {
  const { data, isLoading, error, refetch } = useTrainingRuns(50);
  const runs = data?.items ?? [];
  const active = runs.find((r) => r.id === data?.active_id) ?? null;

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
          <Skeleton className="h-32 bg-hover" />
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
          <ActiveRunCard run={active} hasRuns={runs.length > 0} />
          <RetrainHowTo />
          <RunHistoryTable runs={runs} />
        </>
      )}
    </div>
  );
}

// -- Active run card -------------------------------------------------------

function ActiveRunCard({
  run,
  hasRuns,
}: {
  run: TrainingRun | null;
  hasRuns: boolean;
}) {
  return (
    <section className="mb-7">
      <h2 className="mb-[14px] text-[13px] font-medium text-primary">
        Active run
      </h2>
      <div className="rounded-lg border-[0.5px] border-border-subtle bg-card p-5">
        {!run ? (
          <div className="text-[12px] text-tertiary">
            {hasRuns
              ? "No run currently qualifies as active. The most recent successful run (F1 ≥ 0.5) is loaded into the detector."
              : "No training runs recorded yet. Run the pipeline (see below) to populate this table."}
          </div>
        ) : (
          <>
            <div className="flex flex-wrap items-center gap-3">
              <span className="rounded-md border-[0.5px] border-success/40 bg-success/10 px-2 py-0.5 text-[10px] uppercase tracking-wider text-success">
                active
              </span>
              <span className="font-mono text-[12px] text-secondary">
                run #{run.id}
              </span>
              {run.completed_at && (
                <span className="text-[12px] text-tertiary">
                  · trained {formatTrainingTime(run.completed_at)}
                </span>
              )}
            </div>

            <div className="mt-4 grid grid-cols-1 gap-x-8 gap-y-3 md:grid-cols-3">
              <RunMeta
                icon={<Database size={12} strokeWidth={1.5} />}
                label="Dataset"
                value={run.dataset}
              />
              {run.artifacts_path && (
                <RunMeta
                  icon={<GitBranch size={12} strokeWidth={1.5} />}
                  label="Artifacts"
                  value={run.artifacts_path}
                />
              )}
            </div>

            <div className="mt-5 border-t-[0.5px] border-border-subtle pt-4">
              <div className="mb-2 text-[11px] uppercase tracking-wider text-tertiary">
                Ensemble metrics
              </div>
              <div className="grid grid-cols-3 gap-3">
                <MetricBox label="F1" value={run.f1_score} />
                <MetricBox label="Precision" value={run.precision_score} />
                <MetricBox label="Recall" value={run.recall_score} />
              </div>
            </div>

            {run.notes && (
              <p className="mt-4 max-w-2xl text-[12px] leading-relaxed text-tertiary">
                {run.notes}
              </p>
            )}
          </>
        )}
      </div>
    </section>
  );
}

function RunMeta({
  icon,
  label,
  value,
}: {
  icon?: React.ReactNode;
  label: string;
  value: string;
}) {
  return (
    <div>
      <div className="flex items-center gap-1.5 text-[11px] uppercase tracking-wider text-tertiary">
        {icon}
        {label}
      </div>
      <div className="mt-1 font-mono text-[14px] tabular-nums text-primary">
        {value}
      </div>
    </div>
  );
}

function MetricBox({ label, value }: { label: string; value: number | null }) {
  return (
    <div className="rounded-md border-[0.5px] border-border-subtle bg-page px-3 py-2">
      <div className="text-[11px] text-tertiary">{label}</div>
      <div className="mt-1 font-mono text-[16px] tabular-nums text-primary">
        {value === null ? "—" : value.toFixed(2).replace(/^0/, "")}
      </div>
    </div>
  );
}

// -- Retrain how-to --------------------------------------------------------

function RetrainHowTo() {
  return (
    <section className="mb-7">
      <h2 className="mb-[14px] flex items-center gap-2 text-[13px] font-medium text-primary">
        <Terminal size={14} strokeWidth={1.5} className="text-tertiary" />
        How to retrain
      </h2>
      <div className="rounded-lg border-[0.5px] border-border-subtle bg-card p-5">
        <p className="text-[12px] leading-relaxed text-secondary">
          Models are persisted to{" "}
          <code className="font-mono text-primary">backend/artifacts/</code>.
          To retrain on a different dataset, run the pipeline from the
          backend project root:
        </p>
        <pre className="mt-3 overflow-x-auto rounded-md border-[0.5px] border-border-subtle bg-page px-3 py-2.5 font-mono text-[12px] leading-relaxed text-primary">
          <code>{`cd backend
python -m training.run_full_pipeline --dataset bgl`}</code>
        </pre>
        <p className="mt-3 text-[12px] leading-relaxed text-tertiary">
          The run overwrites{" "}
          <code className="font-mono text-secondary">transformer.pt</code>,{" "}
          <code className="font-mono text-secondary">autoencoder.pt</code>,{" "}
          <code className="font-mono text-secondary">
            confidence_scorer.pt
          </code>{" "}
          and{" "}
          <code className="font-mono text-secondary">thresholds.json</code>{" "}
          in the artifact volume, then inserts a new row into
          training_runs. Restart the Runner and RAG worker afterwards so
          they pick up the new artifacts.
        </p>
      </div>
    </section>
  );
}

// -- Run history -----------------------------------------------------------

function RunHistoryTable({ runs }: { runs: TrainingRun[] }) {
  if (runs.length === 0) {
    return (
      <section>
        <h2 className="mb-[14px] text-[13px] font-medium text-primary">
          Run history
        </h2>
        <div className="rounded-lg border-[0.5px] border-border-subtle bg-card px-5 py-10 text-center text-[12px] text-tertiary">
          No training runs in the database yet.
        </div>
      </section>
    );
  }
  return (
    <section>
      <h2 className="mb-[14px] text-[13px] font-medium text-primary">
        Run history
      </h2>
      <div className="overflow-hidden rounded-lg border-[0.5px] border-border-subtle bg-card">
        <div className="grid grid-cols-[180px_88px_1fr_64px_64px_64px] items-center gap-4 border-b-[0.5px] border-border-subtle px-4 py-2.5 text-[10px] uppercase tracking-wider text-tertiary">
          <div>Trained</div>
          <div>Status</div>
          <div>Dataset</div>
          <div className="text-right">F1</div>
          <div className="text-right">P</div>
          <div className="text-right">R</div>
        </div>
        <div className="divide-y-[0.5px] divide-border-subtle">
          {runs.map((r) => (
            <div
              key={r.id}
              className="grid grid-cols-[180px_88px_1fr_64px_64px_64px] items-center gap-4 px-4 py-3"
            >
              <div className="text-[12px] text-secondary">
                {r.completed_at
                  ? formatTrainingTime(r.completed_at)
                  : "in flight"}
              </div>
              <div>
                <RunStatusPill status={r.status} />
              </div>
              <div className="min-w-0">
                <div className="truncate text-[12px] text-primary">
                  {r.dataset}
                </div>
                {r.notes && (
                  <div className="mt-0.5 truncate text-[11px] text-tertiary">
                    {r.notes}
                  </div>
                )}
              </div>
              <ScoreCell value={r.f1_score} />
              <ScoreCell value={r.precision_score} />
              <ScoreCell value={r.recall_score} />
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

function ScoreCell({ value }: { value: number | null }) {
  if (value === null) {
    return (
      <div className="text-right font-mono text-[12px] tabular-nums text-tertiary">
        —
      </div>
    );
  }
  const className = cn(
    "text-right font-mono text-[12px] tabular-nums",
    value >= 0.9 && "text-success",
    value < 0.9 && value >= 0.5 && "text-warning",
    value < 0.5 && "text-critical",
  );
  return (
    <div className={className}>{value.toFixed(2).replace(/^0/, "")}</div>
  );
}

function RunStatusPill({ status }: { status: TrainingRun["status"] }) {
  if (status === "active") {
    return (
      <span className="inline-flex items-center gap-1 rounded-md border-[0.5px] border-success/40 bg-success/10 px-2 py-0.5 text-[10px] uppercase tracking-wider text-success">
        <CheckCircle2 size={10} strokeWidth={1.75} />
        active
      </span>
    );
  }
  if (status === "failed") {
    return (
      <span className="inline-flex items-center gap-1 rounded-md border-[0.5px] border-critical/40 bg-critical/10 px-2 py-0.5 text-[10px] uppercase tracking-wider text-critical">
        <XCircle size={10} strokeWidth={1.75} />
        failed
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1 rounded-md border-[0.5px] border-border-subtle bg-page px-2 py-0.5 text-[10px] uppercase tracking-wider text-tertiary">
      done
    </span>
  );
}

function formatTrainingTime(iso: string): string {
  const d = new Date(iso);
  return `${d.toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  })} · ${d.toLocaleTimeString(undefined, {
    hour: "2-digit",
    minute: "2-digit",
  })}`;
}
