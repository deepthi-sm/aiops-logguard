import { useAnomaly, useExplanation } from "../hooks/queries";
import { pct, timeAgo } from "../lib/format";
import { SeverityBadge } from "./SeverityBadge";
import { AttentionHeatmap } from "./AttentionHeatmap";
import { FeedbackButtons } from "./FeedbackButtons";

interface Props {
  anomalyId: string | null;
}

export function AnomalyDetail({ anomalyId }: Props) {
  const a = useAnomaly(anomalyId);
  const exp = useExplanation(anomalyId, a.data?.explanation_status);

  if (!anomalyId) {
    return (
      <div className="flex h-full items-center justify-center rounded-lg border border-dashed border-slate-800 bg-slate-900/20 text-sm text-slate-500">
        Select an anomaly to see details
      </div>
    );
  }
  if (!a.data) {
    return (
      <div className="rounded-lg border border-slate-800 bg-slate-900/40 p-4 text-sm text-slate-400">
        Loading anomaly…
      </div>
    );
  }

  const an = a.data;
  return (
    <div className="flex h-full flex-col gap-4 overflow-y-auto rounded-lg border border-slate-800 bg-slate-900/40 p-4">
      <header className="flex flex-wrap items-center gap-3">
        <SeverityBadge severity={an.severity} />
        <span className="font-mono text-sm text-slate-300">{an.source}</span>
        <span className="text-xs text-slate-500">{timeAgo(an.detected_at)}</span>
        <span className="ml-auto rounded bg-slate-800 px-2 py-0.5 font-mono text-[10px] text-slate-400">
          {an.id}
        </span>
      </header>

      <ScoreBar
        ensemble={an.ensemble_score}
        confidence={an.confidence}
        failureProb={an.failure_probability}
        failureWindow={an.predicted_failure_window_min}
      />

      <Section title="Log template (Drain3)">
        <pre className="overflow-x-auto rounded border border-slate-800 bg-slate-900/60 px-3 py-2 font-mono text-xs text-slate-300">
          {an.log_template}
        </pre>
      </Section>

      <Section title="Top contributing lines (attention-weighted)">
        <AttentionHeatmap lines={an.top_contributing_lines} />
      </Section>

      <Section title="Sequence preview">
        <ul className="space-y-px overflow-hidden rounded border border-slate-800 bg-slate-900/60 font-mono text-[11px]">
          {an.sequence_preview.map((line, i) => (
            <li key={i} className="px-3 py-1 text-slate-400">
              {line}
            </li>
          ))}
        </ul>
      </Section>

      <Section title="Root cause (LLaMA + RAG)">
        {an.explanation_status === "failed" && (
          <div className="text-sm text-critical-500">
            Explanation failed to generate.
          </div>
        )}
        {an.explanation_status === "pending" && !exp.data && (
          <div className="flex items-center gap-2 text-sm text-slate-400">
            <Spinner /> Generating…
          </div>
        )}
        {exp.data && (
          <div className="space-y-3">
            <p className="whitespace-pre-wrap rounded border border-slate-800 bg-slate-900/60 p-3 text-sm leading-relaxed text-slate-200">
              {exp.data.root_cause}
            </p>
            <div>
              <h4 className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-400">
                Recommended fix
              </h4>
              <p className="whitespace-pre-wrap rounded border border-slate-800 bg-slate-900/60 p-3 text-sm leading-relaxed text-slate-200">
                {exp.data.recommended_fix}
              </p>
            </div>
            {exp.data.similar_incidents.length > 0 && (
              <div>
                <h4 className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-400">
                  Similar past incidents
                </h4>
                <ul className="space-y-1 text-xs">
                  {exp.data.similar_incidents.map((s) => (
                    <li
                      key={s.incident_id}
                      className="flex items-center justify-between rounded border border-slate-800 bg-slate-900/60 px-3 py-2"
                    >
                      <div className="flex flex-col">
                        <span className="font-mono text-slate-300">
                          {s.incident_id}
                        </span>
                        <span className="font-mono text-[10px] text-slate-500">
                          {s.template}
                        </span>
                      </div>
                      <span className="text-slate-400">
                        {pct(s.similarity_score, 0)} match
                      </span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        )}
      </Section>

      <Section title="Feedback">
        <FeedbackButtons anomalyId={an.id} />
      </Section>
    </div>
  );
}

function ScoreBar({
  ensemble,
  confidence,
  failureProb,
  failureWindow,
}: {
  ensemble: number;
  confidence: number;
  failureProb: number;
  failureWindow: number | null;
}) {
  return (
    <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
      <Score label="Ensemble score" value={pct(ensemble, 0)} />
      <Score label="Confidence" value={pct(confidence, 0)} />
      <Score label="Failure prob" value={pct(failureProb, 0)} />
      <Score
        label="Failure ETA"
        value={failureWindow !== null ? `${failureWindow} min` : "—"}
      />
    </div>
  );
}

function Score({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded border border-slate-800 bg-slate-900/60 px-3 py-2">
      <div className="text-[10px] uppercase tracking-wide text-slate-500">
        {label}
      </div>
      <div className="font-mono text-base text-slate-200">{value}</div>
    </div>
  );
}

function Section({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <section>
      <h3 className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-slate-400">
        {title}
      </h3>
      {children}
    </section>
  );
}

function Spinner() {
  return (
    <span
      aria-hidden
      className="inline-block h-3 w-3 animate-spin rounded-full border border-slate-500 border-t-transparent"
    />
  );
}
