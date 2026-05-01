import type { ReactNode } from "react";
import { cn } from "../lib/cn";
import { EyebrowLabel } from "./EyebrowLabel";

export interface KpiCellProps {
  eyebrow: string;
  value: ReactNode;
  /** Tiny inline trend indicator (e.g. "↑ 12" in success color). */
  trend?: ReactNode;
  /** Sub-label below the big number. */
  subLabel?: ReactNode;
  /** Tailwind class applied to the big-number span. Use this to severity-
   * tint the value (e.g. "text-critical" for the Critical KPI). */
  valueClassName?: string;
}

/**
 * One KPI cell. Three pieces:
 *
 *   <eyebrow uppercase>
 *   <BIG NUMBER>   <↑ trend>
 *   <sub-label tertiary>
 *
 * The big number uses Inter Display 32px / 500 / -0.02em letter-spacing.
 * Numbers should be rendered in mono when they're "data" (scores,
 * percentages) — pass `<span className="font-mono">…</span>` as `value`.
 */
export function KpiCell({
  eyebrow,
  value,
  trend,
  subLabel,
  valueClassName,
}: KpiCellProps) {
  return (
    <div className="flex-1">
      <EyebrowLabel>{eyebrow}</EyebrowLabel>
      <div className="flex items-baseline gap-2.5">
        <span
          className={cn(
            "font-display text-[32px] font-medium leading-none tracking-[-0.02em] text-primary",
            valueClassName,
          )}
        >
          {value}
        </span>
        {trend && <span className="text-xs">{trend}</span>}
      </div>
      {subLabel && (
        <div className="mt-1.5 text-[11px] text-tertiary">{subLabel}</div>
      )}
    </div>
  );
}
