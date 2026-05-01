import type { ConnectionStatus } from "../api/websocket";
import { classes } from "../lib/format";

const LABELS: Record<ConnectionStatus, string> = {
  connecting: "Connecting…",
  open: "Live",
  reconnecting: "Reconnecting…",
  closed: "Offline",
};

const COLORS: Record<ConnectionStatus, string> = {
  open: "bg-emerald-500/20 text-emerald-400 border-emerald-500/40",
  connecting: "bg-amber-500/20 text-amber-400 border-amber-500/40",
  reconnecting: "bg-amber-500/20 text-amber-400 border-amber-500/40",
  closed: "bg-slate-500/20 text-slate-400 border-slate-500/40",
};

const DOT: Record<ConnectionStatus, string> = {
  open: "bg-emerald-400 animate-pulse",
  connecting: "bg-amber-400 animate-pulse",
  reconnecting: "bg-amber-400 animate-pulse",
  closed: "bg-slate-400",
};

export function ConnectionPill({ status }: { status: ConnectionStatus }) {
  return (
    <span
      className={classes(
        "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-medium",
        COLORS[status],
      )}
    >
      <span className={classes("h-2 w-2 rounded-full", DOT[status])} />
      {LABELS[status]}
    </span>
  );
}
