import type { DriftStatus } from "../types";

/**
 * Horizontal drift gauge per spec — three coloured zones along the 0..1
 * range with a marker at the current PSI score:
 *
 *   green (0–0.25)  amber (0.25–0.4)  coral (0.4–1.0)
 *   ──────────────  ────────────────  ──────────────────
 *                 0.12 ▼  ← marker, iris-coloured
 *               0.25            0.40
 *
 * Healthy threshold: PSI < 0.25.
 * Drifting:          0.25–0.4.
 * Retrain needed:    ≥ 0.4.
 *
 * The bar + marker live inside the SVG (which intentionally stretches
 * to fit the container width via `preserveAspectRatio="none"`). The
 * tick labels are rendered as HTML below the SVG so they don't get
 * stretched or clipped by the viewBox.
 */
export function DriftGauge({ drift }: { drift: DriftStatus }) {
  const score = Math.max(0, Math.min(1, drift.drift_score));
  const W = 320;
  const HEIGHT = 18; // marker (12) + a couple px breathing room above the track
  const trackY = 12;

  const greenWidth = 0.25 * W;
  const amberWidth = (0.4 - 0.25) * W;
  const coralWidth = (1 - 0.4) * W;
  const markerX = score * W;

  return (
    <div
      role="img"
      aria-label={`Drift score ${drift.drift_score.toFixed(2)}, status ${drift.status}`}
    >
      <svg
        width="100%"
        height={HEIGHT}
        viewBox={`0 0 ${W} ${HEIGHT}`}
        preserveAspectRatio="none"
        className="block"
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

        {/* Marker — small triangle pointing down at the current value */}
        <g transform={`translate(${markerX}, ${trackY - 4})`}>
          <path d="M 0 0 L -4 -6 L 4 -6 Z" fill="var(--iris)" />
        </g>
      </svg>

      {/* Tick labels — rendered as HTML so they aren't stretched by
          preserveAspectRatio="none" or clipped by the SVG viewBox. */}
      <div className="relative mt-1.5 h-3 font-mono text-[10px] text-tertiary">
        <span
          className="absolute -translate-x-1/2"
          style={{ left: "25%" }}
        >
          0.25
        </span>
        <span
          className="absolute -translate-x-1/2"
          style={{ left: "40%" }}
        >
          0.40
        </span>
      </div>
    </div>
  );
}
