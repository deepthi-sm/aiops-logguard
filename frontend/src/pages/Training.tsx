import { CheckCircle2, Database, GitBranch, XCircle } from "lucide-react";
import { EyebrowLabel } from "../components/EyebrowLabel";
import { cn } from "../lib/cn";

/**
 * /admin/training — model training run history.
 *
 * Top section: the active run (the version actually loaded into
 * detection right now). Below it: a chronological list of past runs.
 * Numbers come straight from `training/RESULTS.md`.
 *
 * Persistence model: each `run_full_pipeline.py` invocation overwrites
 * `backend/artifacts/{transformer,autoencoder,confidence_scorer}.pt`
 * along with `thresholds.json` and `RESULTS.md`. The artifacts dir is
 * a Docker volume (gitignored) — no formal archive system yet, so
 * "previous runs" here are reconstructed from RESULTS.md history,
 * not loaded from a runs table.
 */

interface TrainingRun {
  id: string;
  trained_at: string;
  dataset: string;
  windows: number;
  anomaly_rate: number;
  models: { name: string; f1: number }[];
  ensemble_f1: number;
  status: "active" | "failed";
  note?: string;
}

const RUNS: TrainingRun[] = [
  {
    id: "run_2026_05_01_0819",
    trained_at: "2026-05-01T08:19:00Z",
    dataset: "OpenStack",
    windows: 207_820,
    anomaly_rate: 0.089,
    models: [
      { name: "Transformer", f1: 1.0 },
      { name: "AutoEncoder", f1: 0.99 },
      { name: "ConfidenceMLP", f1: 1.0 },
    ],
    ensemble_f1: 1.0,
    status: "active",
    note: "pos_weight fix landed — class imbalance no longer collapses BCE.",
  },
  {
    id: "run_2026_05_01_0641",
    trained_at: "2026-05-01T06:41:00Z",
    dataset: "OpenStack",
    windows: 207_820,
    anomaly_rate: 0.089,
    models: [
      { name: "Transformer", f1: 0.0 },
      { name: "AutoEncoder", f1: 0.99 },
      { name: "ConfidenceMLP", f1: 0.0 },
    ],
    ensemble_f1: 0.0,
    status: "failed",
    note: "BCE collapsed — model predicted all-negative on 8.9%-positive data.",
  },
];

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

export function Training() {
  const active = RUNS.find((r) => r.status === "active") ?? RUNS[0];

  return (
    <div className="pb-12">
      <header className="mb-7 border-b-[0.5px] border-border-subtle pb-5">
        <EyebrowLabel>Model training</EyebrowLabel>
        <h1 className="text-[22px] font-medium leading-none tracking-[-0.01em] text-primary">
          Training runs
        </h1>
      </header>

      {/* Active run card */}
      <section className="mb-7">
        <h2 className="mb-[14px] text-[13px] font-medium text-primary">
          Active run
        </h2>
        <div className="rounded-lg border-[0.5px] border-border-subtle bg-card p-5">
          <div className="flex flex-wrap items-center gap-3">
            <span className="rounded-md border-[0.5px] border-success/40 bg-success/10 px-2 py-0.5 text-[10px] uppercase tracking-wider text-success">
              active
            </span>
            <span className="font-mono text-[12px] text-secondary">
              {active.id}
            </span>
            <span className="text-[12px] text-tertiary">
              · trained {formatTrainingTime(active.trained_at)}
            </span>
          </div>
          <div className="mt-4 grid grid-cols-1 gap-x-8 gap-y-3 md:grid-cols-3">
            <RunMeta
              icon={<Database size={12} strokeWidth={1.5} />}
              label="Dataset"
              value={active.dataset}
            />
            <RunMeta
              icon={<GitBranch size={12} strokeWidth={1.5} />}
              label="Windows"
              value={active.windows.toLocaleString()}
            />
            <RunMeta
              label="Anomaly rate"
              value={`${(active.anomaly_rate * 100).toFixed(1)}%`}
            />
          </div>
          <div className="mt-5 border-t-[0.5px] border-border-subtle pt-4">
            <div className="mb-2 text-[11px] uppercase tracking-wider text-tertiary">
              Per-model F1
            </div>
            <div className="grid grid-cols-3 gap-3">
              {active.models.map((m) => (
                <div
                  key={m.name}
                  className="rounded-md border-[0.5px] border-border-subtle bg-page px-3 py-2"
                >
                  <div className="text-[11px] text-tertiary">{m.name}</div>
                  <div className="mt-1 font-mono text-[16px] tabular-nums text-primary">
                    {m.f1.toFixed(2).replace(/^0/, "")}
                  </div>
                </div>
              ))}
            </div>
          </div>
          {active.note && (
            <p className="mt-4 max-w-2xl text-[12px] leading-relaxed text-tertiary">
              {active.note}
            </p>
          )}
        </div>
      </section>

      {/* Run history */}
      <section>
        <h2 className="mb-[14px] text-[13px] font-medium text-primary">
          Run history
        </h2>
        <p className="mb-3 max-w-2xl text-[12px] leading-relaxed text-tertiary">
          Each pipeline run overwrites the artifacts in{" "}
          <span className="font-mono text-secondary">backend/artifacts/</span>{" "}
          (a Docker volume, gitignored). Older runs aren't archived to disk —
          this list is reconstructed from{" "}
          <span className="font-mono text-secondary">RESULTS.md</span>.
        </p>
        <div className="overflow-hidden rounded-lg border-[0.5px] border-border-subtle bg-card">
          <div className="grid grid-cols-[180px_88px_120px_100px_88px_1fr] items-center gap-4 border-b-[0.5px] border-border-subtle px-4 py-2.5 text-[10px] uppercase tracking-wider text-tertiary">
            <div>Trained</div>
            <div>Status</div>
            <div>Dataset</div>
            <div className="text-right">Windows</div>
            <div className="text-right">F1</div>
            <div>Note</div>
          </div>
          <div className="divide-y-[0.5px] divide-border-subtle">
            {RUNS.map((r) => (
              <div
                key={r.id}
                className="grid grid-cols-[180px_88px_120px_100px_88px_1fr] items-center gap-4 px-4 py-3"
              >
                <div className="text-[12px] text-secondary">
                  {formatTrainingTime(r.trained_at)}
                </div>
                <div>
                  <RunStatusPill status={r.status} />
                </div>
                <div className="text-[12px] text-primary">{r.dataset}</div>
                <div className="text-right font-mono text-[12px] tabular-nums text-tertiary">
                  {r.windows.toLocaleString()}
                </div>
                <div
                  className={cn(
                    "text-right font-mono text-[12px] tabular-nums",
                    r.ensemble_f1 >= 0.9 && "text-success",
                    r.ensemble_f1 < 0.9 && r.ensemble_f1 >= 0.5 && "text-warning",
                    r.ensemble_f1 < 0.5 && "text-critical",
                  )}
                >
                  {r.ensemble_f1.toFixed(2).replace(/^0/, "")}
                </div>
                <div className="truncate text-[12px] text-tertiary">
                  {r.note ?? "—"}
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>
    </div>
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

function RunStatusPill({ status }: { status: TrainingRun["status"] }) {
  if (status === "active") {
    return (
      <span className="inline-flex items-center gap-1 rounded-md border-[0.5px] border-success/40 bg-success/10 px-2 py-0.5 text-[10px] uppercase tracking-wider text-success">
        <CheckCircle2 size={10} strokeWidth={1.75} />
        active
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1 rounded-md border-[0.5px] border-critical/40 bg-critical/10 px-2 py-0.5 text-[10px] uppercase tracking-wider text-critical">
      <XCircle size={10} strokeWidth={1.75} />
      failed
    </span>
  );
}
