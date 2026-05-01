import { useParams } from "react-router-dom";

/** /anomalies/:id — built out in Step 5 (ScorePanel + ExplanationCard + AttentionLines). */
export function AnomalyDetail() {
  const { id } = useParams<{ id: string }>();
  return (
    <div>
      <div className="text-[11px] text-tertiary">
        Anomalies <span className="text-muted">/</span>{" "}
        <span className="font-mono text-secondary">{id ?? "—"}</span>
      </div>
      <h1 className="mt-1 text-[22px] font-medium tracking-[-0.01em] text-primary">
        Anomaly detail
      </h1>
    </div>
  );
}
