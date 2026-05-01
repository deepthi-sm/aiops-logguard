import type { DriftStatus } from "../types";

/**
 * Horizontal drift gauge per spec — three coloured zones along the 0..1
 * range with a marker at the current PSI score:
 *
 *   green (0–0.25)  amber (0.25–0.4)  coral (0.4–1.0)
 *   ──────────────  ────────────────  ──────────────────
 *                 0.12 ▼  ← marker, iris-coloured
 *
 * Healthy threshold: PSI < 0.25.
 * Drifting:          0.25–0.4.
 * Retrain needed:    ≥ 0.4.
 */
export function DriftGauge({ drift }: { drift: DriftStatus }) {
  const score = Math.max(0, Math.min(1, drift.drift_score));
  // The y-axis offsets are tuned to read well at 32px tall.
  const HEIGHT = 36;
  const W = 320;
  const trackY = 22;

  const greenWidth = 0.25 * W;
  const amberWidth = (0.4 - 0.25) * W;
  const coralWidth = (1 - 0.4) * W;
  const markerX = score * W;

  return (
    <svg
      width="100%"
      height={HEIGHT}
      viewBox={`0 0 ${W} ${HEIGHT}`}
      preserveAspectRatio="none"
      role="img"
      aria-label={`Drift score ${drift.drift_score.toFixed(2)}, status ${drift.status}`}
    >
      {/* Zones */}
      <rect
        x={0}
        y={trackY}
        width={greenWidth}
        height={4}
        fill="var(--severity-success)"
        rx={2}
      />
      <rect
        x={greenWidth}
        y={trackY}
        width={amberWidth}
        height={4}
        fill="var(--severity-warning)"
      />
      <rect
        x={greenWidth + amberWidth}
        y={trackY}
        width={coralWidth}
        height={4}
        fill="var(--severity-critical)"
        rx={2}
      />

      {/* Tick labels at zone boundaries */}
      <text
        x={greenWidth}
        y={trackY + 18}
        fontSize="9"
        fill="var(--text-tertiary)"
        textAnchor="middle"
        fontFamily="JetBrains Mono, monospace"
      >
        0.25
      </text>
      <text
        x={greenWidth + amberWidth}
        y={trackY + 18}
        fontSize="9"
        fill="var(--text-tertiary)"
        textAnchor="middle"
        fontFamily="JetBrains Mono, monospace"
      >
        0.40
      </text>

      {/* Marker — small triangle pointing down at the current value */}
      <g transform={`translate(${markerX}, ${trackY - 6})`}>
        <path d="M 0 0 L -4 -6 L 4 -6 Z" fill="var(--iris)" />
      </g>
    </svg>
  );
}
