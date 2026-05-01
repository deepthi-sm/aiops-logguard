import { useHealth } from "../hooks/queries";
import { ConnectionPill } from "./ConnectionPill";
import type { ConnectionStatus } from "../api/websocket";

export function Header({ wsStatus }: { wsStatus: ConnectionStatus }) {
  const health = useHealth();
  return (
    <header className="border-b border-slate-800 bg-slate-900/60 backdrop-blur">
      <div className="mx-auto flex max-w-7xl items-center justify-between px-6 py-3">
        <div className="flex items-center gap-3">
          <div className="text-lg font-semibold tracking-tight">
            AIOps<span className="text-info-500">-</span>LogGuard
          </div>
          {health.data && (
            <span className="font-mono text-xs text-slate-400">
              v{health.data.version}
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          {health.data && (
            <span className="text-xs text-slate-400">
              uptime {Math.floor(health.data.uptime_s / 60)}m
            </span>
          )}
          <ConnectionPill status={wsStatus} />
        </div>
      </div>
    </header>
  );
}
