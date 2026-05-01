import { Fragment, type ReactNode } from "react";
import { Children } from "react";

/**
 * Horizontal KPI strip with hairline vertical dividers between cells —
 * NEVER card walls. Per spec rule #1: "No card walls between KPIs. Use
 * thin vertical dividers."
 *
 * Pass `<KpiCell>` children directly; this wrapper handles the dividers.
 */
export function KpiBar({ children }: { children: ReactNode }) {
  const cells = Children.toArray(children);
  return (
    <div className="mb-7 flex gap-7">
      {cells.map((cell, i) => (
        <Fragment key={i}>
          {i > 0 && <div className="w-px bg-border-subtle" aria-hidden />}
          {cell}
        </Fragment>
      ))}
    </div>
  );
}
