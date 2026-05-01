import { useExplanation } from "../api/queries";
import type { ExplanationStatus } from "../types";
import { EyebrowLabel } from "./EyebrowLabel";
import { Logo } from "./Logo";
import { Skeleton } from "./Skeleton";

/**
 * The most "wow" component in the demo — the LLaMA-generated root-cause
 * explanation with retrieved similar incidents. Per spec:
 *
 *   ⬢ Root cause analysis    LLaMA 3 · N incidents retrieved
 *   ┌──────────────────────────────────────────────────────┐
 *   │ <root cause paragraph>                                │
 *   │                                                       │
 *   │ RECOMMENDED FIX                                       │
 *   │ 1. ...                                                │
 *   │ 2. ...                                                │
 *   │                                                       │
 *   │ SIMILAR PAST INCIDENTS                                │
 *   │ inc_247  ERROR …                            91% match │
 *   └──────────────────────────────────────────────────────┘
 */
export function ExplanationCard({
  anomalyId,
  status,
}: {
  anomalyId: string;
  status: ExplanationStatus;
}) {
  const { data, isLoading, error } = useExplanation(anomalyId, status);
  const incidentCount = data?.similar_incidents.length ?? 0;

  return (
    <section className="mb-7">
      <div className="mb-[14px] flex items-center gap-2">
        <span className="text-iris">
          <Logo size={14} />
        </span>
        <h2 className="text-[13px] font-medium text-primary">
          Root cause analysis
        </h2>
        <span className="text-[11px] text-tertiary">
          LLaMA 3 · {incidentCount} incidents retrieved
        </span>
      </div>

      <div className="rounded-lg border-[0.5px] border-border-subtle bg-card p-5">
        {status === "pending" && <PendingState />}
        {status === "failed" && <FailedState />}
        {status === "ready" && isLoading && !data && (
          <div className="space-y-2">
            <Skeleton className="h-3 bg-hover" />
            <Skeleton className="h-3 w-[85%] bg-hover" />
            <Skeleton className="h-3 w-[70%] bg-hover" />
          </div>
        )}
        {status === "ready" && error && (
          <div className="text-[13px] text-critical">{(error as Error).message}</div>
        )}
        {status === "ready" && data && <ReadyContent data={data} />}
      </div>
    </section>
  );
}

// -- Sub-states ------------------------------------------------------------

function PendingState() {
  return (
    <div>
      <div className="mb-3 flex items-center gap-2 text-[12px] text-tertiary">
        <Spinner />
        LLaMA is analysing this anomaly…
      </div>
      <div className="space-y-2">
        <Skeleton className="h-3 bg-hover" />
        <Skeleton className="h-3 w-[85%] bg-hover" />
        <Skeleton className="h-3 w-[60%] bg-hover" />
      </div>
    </div>
  );
}

function FailedState() {
  return (
    <div className="text-[13px] text-critical">
      Explanation failed to generate. The model may be down or rate-limited
      — see <span className="font-mono">/api/v1/system/drift</span> for status.
    </div>
  );
}

function ReadyContent({
  data,
}: {
  data: NonNullable<ReturnType<typeof useExplanation>["data"]>;
}) {
  return (
    <>
      <p className="whitespace-pre-wrap text-[14px] leading-relaxed text-primary">
        {data.root_cause}
      </p>

      <div className="mt-5">
        <EyebrowLabel>Recommended fix</EyebrowLabel>
        <div className="whitespace-pre-wrap text-[13px] leading-[1.8] text-primary">
          {data.recommended_fix}
        </div>
      </div>

      {data.similar_incidents.length > 0 && (
        <div className="mt-5">
          <EyebrowLabel>Similar past incidents</EyebrowLabel>
          <div className="space-y-1.5">
            {data.similar_incidents.map((inc) => (
              <div
                key={inc.incident_id}
                className="flex items-center justify-between gap-3 rounded-md border-[0.5px] border-border-subtle bg-page px-3 py-2"
              >
                <div className="min-w-0 flex-1">
                  <div className="font-mono text-[12px] text-secondary">
                    {inc.incident_id}
                  </div>
                  <div className="mt-0.5 truncate font-mono text-[11px] text-tertiary">
                    {inc.template}
                  </div>
                </div>
                <div className="shrink-0 font-mono text-[12px] tabular-nums text-tertiary">
                  {(inc.similarity_score * 100).toFixed(0)}% match
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </>
  );
}

function Spinner() {
  return (
    <span
      aria-hidden
      className="inline-block h-3 w-3 animate-spin rounded-full border border-tertiary border-t-transparent"
    />
  );
}
