import {
  useDrift,
  useSystemQueue,
  useSystemServices,
  useTrainingRuns,
} from "../api/queries";
import { DriftGauge } from "../components/DriftGauge";
import { ErrorState } from "../components/ErrorState";
import { EyebrowLabel } from "../components/EyebrowLabel";
import { ServiceCard } from "../components/ServiceCard";
import { Skeleton } from "../components/Skeleton";
import { cn } from "../lib/cn";
import { driftClassName, driftLabel } from "../lib/severity";
import type {
  DriftStatus,
  SystemQueueResponse,
  TrainingRun,
} from "../types";

/**
 * /admin/system — the "is the engine running?" page. Four sections:
 *
 *   1. Embedding drift (PSI) — synthetic-mode score banded into
 *      healthy / drift_high / drift_critical (Phase 2B). Already live.
 *   2. Services — live probes via GET /api/v1/system/services. Each
 *      card shows status (online / degraded / offline) + a one-line
 *      detail. The RAG worker has no inbound port so it's surfaced
 *      indirectly through the queue panel below, not here.
 *   3. Pending explanation queue — GET /api/v1/system/queue. Shows
 *      pending / ready / failed counts plus the oldest pending row
 *      so an operator can see whether the worker is keeping up.
 *   4. Active models — wired to the active training run from
 *      GET /api/v1/training/runs. Per-model F1/P/R uses the active
 *      run's ensemble metrics (training_runs only stores ensemble-level
 *      numbers; surfacing the same value across all three rows is
 *      the honest representation given that schema). Three-decimal
 *      precision and the same "saturated" framing we use on the
 *      Training page.
 */
export function System() {
  const drift = useDrift();
  return (
    <div className="pb-12">
      <Header />
      <DriftSection
        drift={drift.data}
        loading={drift.isLoading}
        error={drift.error as Error | null}
        onRetry={() => drift.refetch()}
      />
      <ServicesGridLive />
      <QueueSection />
      <ActiveModelsLive />
    </div>
  );
}

// -- Header ----------------------------------------------------------------

function Header() {
  return (
    <header className="mb-7 flex items-end justify-between border-b-[0.5px] border-border-subtle pb-5">
      <div>
        <EyebrowLabel>Model & infrastructure</EyebrowLabel>
        <h1 className="text-[22px] font-medium leading-none tracking-[-0.01em] text-primary">
          System health
        </h1>
      </div>
      <div className="text-[11px] text-tertiary">Live</div>
    </header>
  );
}

// -- Drift -----------------------------------------------------------------

function DriftSection({
  drift,
  loading,
  error,
  onRetry,
}: {
  drift: DriftStatus | undefined;
  loading: boolean;
  error: Error | null;
  onRetry: () => void;
}) {
  return (
    <section className="mb-7">
      <h2 className="mb-[14px] text-[13px] font-medium text-primary">
        Embedding drift (PSI)
      </h2>
      <div className="rounded-lg border-[0.5px] border-border-subtle bg-card p-5">
        {loading && <Skeleton className="h-24 bg-hover" />}
        {error && <ErrorState message={error.message} onRetry={onRetry} />}
        {drift && (
          <div className="flex flex-col gap-5 md:flex-row md:items-center md:justify-between">
            <div className="flex-1">
              <div className="flex items-end gap-3">
                <span
                  className={cn(
                    "font-display text-[44px] font-medium leading-none tracking-[-0.02em]",
                    driftClassName(drift.status),
                  )}
                >
                  {drift.drift_score.toFixed(2)}
                </span>
                <span
                  className={cn(
                    "rounded-md border-[0.5px] px-2 py-0.5 text-[11px] uppercase tracking-wider",
                    drift.status === "healthy" &&
                      "border-success/40 bg-success/10 text-success",
                    drift.status === "drift_high" &&
                      "border-warning/40 bg-warning/10 text-warning",
                    drift.status === "drift_critical" &&
                      "border-critical/40 bg-critical/10 text-critical",
                  )}
                >
                  {driftLabel(drift.status)}
                </span>
              </div>
              <p className="mt-3 max-w-md text-[12px] leading-relaxed text-tertiary">
                Population Stability Index between training and live
                embeddings.
              </p>
            </div>
            <div className="md:w-1/2 md:max-w-[320px]">
              <DriftGauge drift={drift} />
            </div>
          </div>
        )}
      </div>
    </section>
  );
}

// -- Services (live) -------------------------------------------------------

function ServicesGridLive() {
  const { data, isLoading, error, refetch } = useSystemServices();
  return (
    <section className="mb-7">
      <h2 className="mb-[14px] text-[13px] font-medium text-primary">
        Services
      </h2>
      {isLoading && (
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
          <Skeleton className="h-20 bg-hover" />
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
      {data && (
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
          {data.items.map((s) => (
            <ServiceCard
              key={s.name}
              name={s.name}
              status={s.status}
              detail={s.detail}
            />
          ))}
        </div>
      )}
    </section>
  );
}

// -- Pending queue panel (live) -------------------------------------------

function QueueSection() {
  const { data, isLoading, error, refetch } = useSystemQueue();
  return (
    <section className="mb-7">
      <h2 className="mb-[14px] text-[13px] font-medium text-primary">
        Pending explanation queue
      </h2>
      <div className="rounded-lg border-[0.5px] border-border-subtle bg-card p-5">
        {isLoading && <Skeleton className="h-12 bg-hover" />}
        {error && (
          <ErrorState
            message={(error as Error).message}
            onRetry={() => refetch()}
          />
        )}
        {data && <QueueBody data={data} />}
      </div>
    </section>
  );
}

function QueueBody({ data }: { data: SystemQueueResponse }) {
  const total = data.pending + data.ready + data.failed;
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-x-8 gap-y-3">
        <QueueStat label="Pending" value={data.pending} accent="warning" />
        <QueueStat label="Ready" value={data.ready} accent="success" />
        <QueueStat label="Failed" value={data.failed} accent="critical" />
        <QueueStat label="Total" value={total} accent="muted" />
      </div>
      {data.oldest_pending_id ? (
        <div className="border-t-[0.5px] border-border-subtle pt-3 text-[12px] text-tertiary">
          Oldest pending:{" "}
          <span className="font-mono text-secondary">
            {data.oldest_pending_id}
          </span>
          {data.oldest_pending_at && (
            <>
              {" · "}
              <span title={new Date(data.oldest_pending_at).toLocaleString()}>
                detected {formatAgo(data.oldest_pending_at)}
              </span>
            </>
          )}
        </div>
      ) : (
        <div className="border-t-[0.5px] border-border-subtle pt-3 text-[12px] text-tertiary">
          No pending explanations — the RAG worker has caught up.
        </div>
      )}
    </div>
  );
}

function QueueStat({
  label,
  value,
  accent,
}: {
  label: string;
  value: number;
  accent: "success" | "warning" | "critical" | "muted";
}) {
  const colour =
    accent === "success"
      ? "text-success"
      : accent === "warning"
        ? value > 0
          ? "text-warning"
          : "text-tertiary"
        : accent === "critical"
          ? value > 0
            ? "text-critical"
            : "text-tertiary"
          : "text-secondary";
  return (
    <div>
      <div className="text-[10px] uppercase tracking-wider text-tertiary">
        {label}
      </div>
      <div
        className={cn(
          "mt-0.5 font-mono text-[20px] tabular-nums",
          colour,
        )}
      >
        {value.toLocaleString()}
      </div>
    </div>
  );
}

function formatAgo(iso: string): string {
  const ms = Date.now() - new Date(iso).getTime();
  if (!Number.isFinite(ms) || ms < 0) return "just now";
  const sec = Math.round(ms / 1000);
  if (sec < 60) return `${sec}s ago`;
  const min = Math.round(sec / 60);
  if (min < 60) return `${min}m ago`;
  const hr = Math.round(min / 60);
  if (hr < 24) return `${hr}h ago`;
  return `${Math.round(hr / 24)}d ago`;
}

// -- Active models (live) --------------------------------------------------

interface ActiveModelRow {
  name: string;
  filename: string;
  config: string;
}

const MODEL_ROWS: ActiveModelRow[] = [
  {
    name: "Transformer",
    filename: "transformer.pt",
    config: "4 layers · 8 heads · d_model 256",
  },
  {
    name: "AutoEncoder",
    filename: "autoencoder.pt",
    config: "384 → 64 → 384 · normal-only",
  },
  {
    name: "Confidence MLP",
    filename: "confidence_scorer.pt",
    config: "MLP 2 → 16 → 8 → 1 sigmoid",
  },
];

function ActiveModelsLive() {
  const { data, isLoading, error, refetch } = useTrainingRuns(50);
  const active = data?.items.find((r) => r.id === data.active_id) ?? null;

  return (
    <section>
      <h2 className="mb-[14px] text-[13px] font-medium text-primary">
        Active models
      </h2>
      {isLoading && <Skeleton className="h-32 bg-hover" />}
      {error && (
        <ErrorState
          message={(error as Error).message}
          onRetry={() => refetch()}
        />
      )}
      {!isLoading && !error && (
        <ActiveModelsBody active={active} />
      )}
    </section>
  );
}

function ActiveModelsBody({ active }: { active: TrainingRun | null }) {
  if (!active) {
    return (
      <div className="rounded-lg border-[0.5px] border-border-subtle bg-card px-5 py-4 text-[12px] text-tertiary">
        No active training run. Train a model to populate this section.
      </div>
    );
  }

  return (
    <div className="divide-y-[0.5px] divide-border-subtle overflow-hidden rounded-lg border-[0.5px] border-border-subtle bg-card">
      {/* Caveat banner: training_runs stores ensemble-level metrics
          only, so each model row carries the same numbers. Surfaced
          honestly here so a reader doesn't think the three identical
          values across rows is a per-model breakdown. */}
      <div className="flex items-center justify-between gap-3 bg-page px-4 py-2 text-[11px] text-tertiary">
        <span>
          Per-model breakdown not stored — the values below are the
          ensemble metrics from the active run (
          <span className="font-mono">{active.dataset}</span>).
        </span>
      </div>
      {MODEL_ROWS.map((m) => (
        <div
          key={m.name}
          className="flex items-center justify-between gap-6 p-4"
        >
          <div className="min-w-0 flex-1">
            <div className="text-[13px] font-medium text-primary">
              {m.name}
            </div>
            <div className="mt-1 truncate font-mono text-[11px] text-tertiary">
              {m.filename} · {m.config}
            </div>
          </div>
          <div className="flex shrink-0 gap-6">
            <ModelStat label="F1" value={active.f1_score} />
            <ModelStat label="P" value={active.precision_score} />
            <ModelStat label="R" value={active.recall_score} />
          </div>
        </div>
      ))}
    </div>
  );
}

function ModelStat({ label, value }: { label: string; value: number | null }) {
  const saturated = value !== null && value >= 0.999;
  const colour = value === null
    ? "text-tertiary"
    : saturated
      ? "text-secondary"   // neutral, no green for ceiling-pegged values
      : value >= 0.9
        ? "text-success"
        : value >= 0.5
          ? "text-warning"
          : "text-critical";
  return (
    <div className="text-right">
      <div className="text-[10px] uppercase tracking-wider text-tertiary">
        {label}
      </div>
      <div
        className={cn(
          "font-mono text-[14px] tabular-nums",
          colour,
        )}
      >
        {value === null ? "—" : value.toFixed(3)}
      </div>
    </div>
  );
}
