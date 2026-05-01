import type { Severity } from "../api/types";
import { classes, severityColor } from "../lib/format";

export function SeverityBadge({ severity }: { severity: Severity }) {
  return (
    <span
      className={classes(
        "inline-flex items-center rounded-md border px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider",
        severityColor(severity),
      )}
    >
      {severity}
    </span>
  );
}
