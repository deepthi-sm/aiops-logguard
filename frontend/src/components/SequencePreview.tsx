import { ChevronRight } from "lucide-react";
import { useState } from "react";
import { cn } from "../lib/cn";
import {
  logLineAttentionBackground,
  logLineFaintBackground,
} from "../lib/severity";
import type { ContributingLine } from "../types";
import { LogLine } from "./LogLine";

/**
 * Collapsible "Full sequence (20 events)" block. Closed by default to keep
 * the detail page scannable. When expanded, shows all 20 lines from
 * `sequence_preview` mono-formatted with line numbers; lines that ALSO
 * appear in `top_contributing_lines` get the same coral attention shading
 * as the AttentionLines component above so the user can spot them in context.
 */
export function SequencePreview({
  lines,
  contributingLines,
}: {
  lines: string[];
  contributingLines: ContributingLine[];
}) {
  const [open, setOpen] = useState(false);

  // Map raw line text → attention so we can shade matching rows below.
  const attentionByLine = new Map(
    contributingLines.map((c) => [c.line, c.attention]),
  );

  return (
    <section className="mb-7">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="mb-[14px] flex items-center gap-2 text-[13px] font-medium text-primary transition-colors hover:text-secondary"
      >
        <ChevronRight
          size={14}
          strokeWidth={1.5}
          className={cn("transition-transform", open && "rotate-90")}
        />
        Full sequence ({lines.length} events)
      </button>

      {open && (
        <div className="overflow-hidden rounded-lg border-[0.5px] border-border-subtle bg-card">
          {lines.map((line, i) => {
            const attention = attentionByLine.get(line);
            // Lines that drove the model's verdict get the strong
            // level-tinted attention shading; every other line gets a faint
            // tint of its own level color so INFO/WARN/ERROR are at least
            // visually distinguishable.
            const background =
              attention !== undefined
                ? logLineAttentionBackground(line, attention)
                : logLineFaintBackground(line);
            const style = background ? { background } : undefined;
            return (
              <div
                key={i}
                style={style}
                className={cn(
                  "flex items-start gap-3 px-3.5 py-1.5 font-mono text-[11px]",
                  i < lines.length - 1 && "border-b-[0.5px] border-border-subtle",
                )}
              >
                <span className="w-6 shrink-0 text-right tabular-nums text-tertiary">
                  {i + 1}
                </span>
                <LogLine line={line} className="break-all text-primary" />
              </div>
            );
          })}
        </div>
      )}
    </section>
  );
}
