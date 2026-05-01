import { useDrift } from "../api/queries";
import { DriftGauge } from "../components/DriftGauge";
import { ErrorState } from "../components/ErrorState";
import { EyebrowLabel } from "../components/EyebrowLabel";
import {
  ServiceCard,
  type ServiceCardProps,
  type ServiceStatus,
} from "../components/ServiceCard";
import { Skeleton } from "../components/Skeleton";
import { cn } from "../lib/cn";
import { driftClassName, driftLabel } from "../lib/severity";
import type { DriftStatus } from "../types";

/**
 * /system — the "is the engine running?" page. Three sections:
 *
 *   1. Drift status — big mono number + status pill + horizontal gauge SVG
 *      with green / amber / coral zones at 0–0.25 / 0.25–0.4 / 0.4–1.0.
 *   2. Services grid — one card per dependency (FastAPI, RAG worker,
 *      Redis, Ollama, Postgres). Status hardcoded for now; PR for live
 *      polling lands when there's a `/api/v1/system/services` endpoint.
 *   3. Active models table — the artefact files this run trained, with
 *      F1 / P / R columns lifted straight from the paper-grade results.
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
      <ServicesGrid />
      <ModelsTable />
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
      <div className="text-[11px] text-tertiary">Updated just now</div>
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
                embeddings. Last retrain{" "}
                {drift.last_retrain
                  ? new Date(drift.last_retrain).toLocaleDateString()
                  : "—"}{" "}
                on the OpenStack dataset.
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

// -- Services --------------------------------------------------------------

const SERVICES: ServiceCardProps[] = [
  {
    name: "FastAPI backend",
    status: "online",
    detail: "localhost:8000 · v0.1.0 · /api/v1",
  },
  {
    name: "RAG worker",
    status: "online",
    detail: "subscribed to anomalies:detected · 0 in flight",
  },
  {
    name: "Redis streams",
    status: "online",
    detail: "redis:6379 · streams: logs:raw · anomalies:broadcast",
  },
  {
    name: "Ollama / LLaMA 3 8B",
    status: "online",
    detail: "ollama:11434 · model: llama3:8b · cached: 12 prompts",
  },
  {
    name: "Postgres",
    status: "online",
    detail: "postgres:5432 · db: logguard · 4 tables",
  },
];

function ServicesGrid() {
  return (
    <section className="mb-7">
      <h2 className="mb-[14px] text-[13px] font-medium text-primary">Services</h2>
      <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
        {SERVICES.map((s) => (
          <ServiceCard key={s.name} {...s} />
        ))}
      </div>
    </section>
  );
}

// -- Models ----------------------------------------------------------------

interface ModelRow {
  name: string;
  filename: string;
  config: string;
  f1: number;
  precision: number;
  recall: number;
}

// These numbers are lifted straight from the user's `training/RESULTS.md` —
// the post-pos_weight-fix run. When real eval rows are exposed via an API
// endpoint, swap this hardcoded list for a useQuery hook.
const MODELS: ModelRow[] = [
  {
    name: "Transformer",
    filename: "transformer.pt",
    config: "4 layers · 8 heads · d_model 256",
    f1: 1.0,
    precision: 1.0,
    recall: 1.0,
  },
  {
    name: "AutoEncoder",
    filename: "autoencoder.pt",
    config: "384 → 64 → 384 · normal-only",
    f1: 0.99,
    precision: 0.99,
    recall: 0.99,
  },
  {
    name: "Confidence MLP",
    filename: "confidence_scorer.pt",
    config: "MLP 2 → 16 → 8 → 1 sigmoid",
    f1: 1.0,
    precision: 1.0,
    recall: 1.0,
  },
];

function ModelsTable() {
  return (
    <section>
      <h2 className="mb-[14px] text-[13px] font-medium text-primary">
        Active models
      </h2>
      <div className="divide-y-[0.5px] divide-border-subtle overflow-hidden rounded-lg border-[0.5px] border-border-subtle bg-card">
        {MODELS.map((m) => (
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
              <ModelStat label="F1" value={m.f1} />
              <ModelStat label="P" value={m.precision} />
              <ModelStat label="R" value={m.recall} />
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}

function ModelStat({ label, value }: { label: string; value: number }) {
  return (
    <div className="text-right">
      <div className="text-[10px] uppercase tracking-wider text-tertiary">
        {label}
      </div>
      <div className="font-mono text-[14px] tabular-nums text-primary">
        {value.toFixed(2).replace(/^0/, "")}
      </div>
    </div>
  );
}
