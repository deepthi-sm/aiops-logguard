import type { Anomaly } from "../types";
import { formatScoreDecimal } from "../lib/format";
import { KpiBar } from "./KpiBar";
import { KpiCell } from "./KpiCell";

/**
 * Four-cell score panel for the AnomalyDetail page. Reuses KpiBar (with the
 * spec's hairline vertical dividers — never card walls) and shows raw
 * decimal scores in mono so they look like data, not commentary.
 *
 *    ENSEMBLE        CONFIDENCE        FAILURE PROB        PREDICTED IN
 *    .94             .91               .82                 12m
 */
export function ScorePanel({ anomaly }: { anomaly: Anomaly }) {
  const failureWindow = anomaly.predicted_failure_window_min;
  return (
    <KpiBar>
      <KpiCell
        eyebrow="Ensemble score"
        value={
          <span className="font-mono">
            {formatScoreDecimal(anomaly.ensemble_score)}
          </span>
        }
      />
      <KpiCell
        eyebrow="Confidence"
        value={
          <span className="font-mono">
            {formatScoreDecimal(anomaly.confidence)}
          </span>
        }
      />
      <KpiCell
        eyebrow="Failure probability"
        value={
          <span className="font-mono">
            {formatScoreDecimal(anomaly.failure_probability)}
          </span>
        }
      />
      <KpiCell
        eyebrow="Predicted in"
        value={
          <span className="font-mono text-anomaly">
            {failureWindow !== null ? `${failureWindow}m` : "—"}
          </span>
        }
      />
    </KpiBar>
  );
}
