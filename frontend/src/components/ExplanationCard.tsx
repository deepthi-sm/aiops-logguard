import { useEffect, useState } from "react";
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
  const { data, error } = useExplanation(anomalyId, status);
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
        {/* Rendering is data-driven, not status-prop-driven.
            useAnomaly polls every 2 s while the explanation is
            pending so its `status` prop catches up, but useExplanation
            polls every 500 ms and will have the Explanation in hand
            up to ~2 s earlier. We render based on what we actually
            have so the user sees the explanation the instant it
            arrives, without waiting for the parent anomaly query to
            tick. The status prop is a hint about which "empty"
            placeholder to show, never about whether to render
            ReadyContent. */}
        {data ? (
          <ReadyContent data={data} />
        ) : error ? (
          <FailedState error={error} />
        ) : status === "failed" ? (
          <FailedState error={null} />
        ) : (
          <PendingState />
        )}
      </div>
    </section>
  );
}

// -- Sub-states ------------------------------------------------------------

/**
 * "LLaMA is analysing this anomaly…" with a live elapsed counter.
 *
 * Why a counter: a flat skeleton looks identical at 5 s and 5 min, so
 * any explanation slow enough to notice "looks broken." Showing
 * elapsed time tells the viewer the system is working and gives them
 * a reasonable way to decide when something has gone wrong.
 *
 * The clock starts on mount, so it reflects "time you've been waiting
 * on this page" rather than "time since the worker queued the job."
 * For the demo that's the more relevant number.
 */
function PendingState() {
  const [elapsed, setElapsed] = useState(0);
  useEffect(() => {
    const start = Date.now();
    const id = window.setInterval(() => {
      setElapsed(Math.floor((Date.now() - start) / 1000));
    }, 1000);
    return () => window.clearInterval(id);
  }, []);

  const elapsedStr =
    elapsed < 60
      ? `${elapsed}s`
      : `${Math.floor(elapsed / 60)}m ${(elapsed % 60).toString().padStart(2, "0")}s`;

  return (
    <div>
      <div className="mb-3 flex items-center gap-2 text-[12px] text-tertiary">
        <Spinner />
        <span>
          LLaMA is analysing this anomaly…{" "}
          <span className="font-mono tabular-nums text-secondary">({elapsedStr})</span>
        </span>
      </div>
      <div className="space-y-2">
        <Skeleton className="h-3 bg-hover" />
        <Skeleton className="h-3 w-[85%] bg-hover" />
        <Skeleton className="h-3 w-[60%] bg-hover" />
      </div>
      {elapsed >= 60 && elapsed < 300 && (
        <div className="mt-3 text-[11px] text-tertiary">
          Generation can take a couple of minutes on CPU. The pipeline
          times out after 15 minutes, after which this card will switch
          to an error state.
        </div>
      )}
      {elapsed >= 300 && (
        <div className="mt-3 text-[11px] text-warning">
          This is taking longer than expected. The model may be cold
          or under load. The pipeline will mark this as failed at
          15 minutes if it doesn't finish.
        </div>
      )}
    </div>
  );
}

/**
 * Failed state — surfaces when the worker has set
 * `explanation_status='failed'` (LLaMA timeout / connection failure /
 * malformed response). When the user clicks again the API will queue
 * a fresh attempt, but we don't auto-retry to avoid stampeding a
 * model that's already struggling.
 */
function FailedState({ error }: { error?: Error | null }) {
  // Surface the API's `detail` message when present — useful for
  // operators reading the page during a demo to tell timeout vs. a
  // genuine generation error apart.
  const detail = error?.message?.trim();
  return (
    <div className="text-[13px] text-critical">
      <div>
        Explanation generation failed. The model timed out or returned
        an error before producing a postmortem.
      </div>
      {detail && detail !== "Explanation generation failed" && (
        <div className="mt-2 font-mono text-[11px] text-tertiary">{detail}</div>
      )}
      <div className="mt-2 text-[11px] text-tertiary">
        Click another anomaly, or refresh this page to queue a fresh
        attempt. Check the <span className="font-mono">LogGuard RAG</span>{" "}
        worker logs for the failed call (search for{" "}
        <span className="font-mono">rid={"{anomaly_id}"}</span>).
      </div>
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

      <div className="mt-5">
        <EyebrowLabel>Similar past incidents</EyebrowLabel>
        {data.similar_incidents.length === 0 ? (
          <div className="rounded-md border-[0.5px] border-border-subtle bg-page px-3 py-3 text-[12px] text-tertiary">
            No similar incidents found in the FAISS index for this anomaly.
          </div>
        ) : (
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
        )}
      </div>
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
