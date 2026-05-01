import type { ContributingLine } from "../api/types";

/**
 * Renders a window's `top_contributing_lines` with shading proportional to
 * each line's `attention` weight. The most-attended lines are visually
 * obvious — that's the explainability story for the paper.
 */
export function AttentionHeatmap({ lines }: { lines: ContributingLine[] }) {
  if (!lines.length) {
    return (
      <div className="rounded border border-slate-800 bg-slate-900/40 p-3 text-xs text-slate-500">
        No per-line attention available.
      </div>
    );
  }
  // Normalise so the largest weight maps to full opacity. (Backend already
  // normalises but we re-normalise locally to be safe — UI never blanks out.)
  const max = Math.max(...lines.map((l) => l.attention), 1e-6);
  return (
    <div className="space-y-px overflow-hidden rounded border border-slate-800 bg-slate-900/40 font-mono text-[11px]">
      {lines.map((l, i) => {
        const intensity = l.attention / max;
        // Shift hue toward critical-red proportional to attention.
        const bg = `rgba(239, 68, 68, ${(intensity * 0.45).toFixed(3)})`;
        return (
          <div
            key={i}
            className="flex items-start gap-2 px-3 py-1"
            style={{ background: bg }}
          >
            <span className="w-12 shrink-0 text-right text-slate-500">
              {(l.attention * 100).toFixed(0)}%
            </span>
            <span className="flex-1 break-all text-slate-200">{l.line}</span>
          </div>
        );
      })}
    </div>
  );
}
