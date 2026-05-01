import { logLineAttentionBackground } from "../lib/severity";
import type { ContributingLine } from "../types";
import { LogLine } from "./LogLine";

/**
 * Coral-shaded attention heatmap — the explainability story made visible.
 *
 * Per spec rule:
 *   - Mono font, 11px
 *   - Background: rgba(251, 113, 133, attention) — coral with attention as alpha
 *   - Linear scaling (NOT square root) — user wants the dramatic effect
 *   - Cap alpha at 0.6 so even the hottest line stays readable
 *   - For accessibility: also output the score in tertiary text — color
 *     alone isn't enough.
 */
export function AttentionLines({ lines }: { lines: ContributingLine[] }) {
  return (
    <section className="mb-7">
      <div className="mb-[14px] flex items-end justify-between">
        <h2 className="text-[13px] font-medium text-primary">
          Top contributing log lines
        </h2>
        <span className="text-[11px] text-tertiary">attention weighted</span>
      </div>

      {lines.length === 0 ? (
        <div className="rounded-lg border-[0.5px] border-border-subtle bg-card px-4 py-6 text-center text-[12px] text-tertiary">
          No per-line attention available.
        </div>
      ) : (
        <div className="space-y-1">
          {lines.map((l, i) => (
            <div
              key={i}
              style={{ background: logLineAttentionBackground(l.line, l.attention) }}
              className="flex items-start gap-3 rounded px-3.5 py-2 font-mono text-[11px]"
            >
              <LogLine
                line={l.line}
                className="min-w-0 flex-1 break-all text-primary"
              />
              <span className="shrink-0 font-mono tabular-nums text-tertiary">
                {l.attention.toFixed(2)}
              </span>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}
