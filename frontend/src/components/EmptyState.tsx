import type { ReactNode } from "react";

/**
 * Inline empty-state placeholder — used inside cards/sections when a
 * collection has no items. Specific message per spec ("No anomalies in
 * the last hour — system is healthy"), not a generic "Nothing here".
 */
export function EmptyState({
  message,
  action,
}: {
  message: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center justify-center px-4 py-10 text-center">
      <div className="text-[13px] text-tertiary">{message}</div>
      {action && <div className="mt-3">{action}</div>}
    </div>
  );
}
