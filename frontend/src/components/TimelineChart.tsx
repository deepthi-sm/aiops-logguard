import { useState } from "react";
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { useTimeline } from "../hooks/queries";
import type { TimelineWindow } from "../api/types";
import { classes } from "../lib/format";

const WINDOW_OPTIONS: { value: TimelineWindow; label: string }[] = [
  { value: "1h", label: "1h" },
  { value: "24h", label: "24h" },
  { value: "7d", label: "7d" },
];

export function TimelineChart() {
  const [window, setWindow] = useState<TimelineWindow>("24h");
  const timeline = useTimeline(window);

  const data =
    timeline.data?.buckets.map((b) => ({
      ts: new Date(b.ts).getTime(),
      critical: b.critical,
      warning: b.warning,
      info: b.info,
    })) ?? [];

  return (
    <div className="rounded-lg border border-slate-800 bg-slate-900/40 p-4">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-sm font-semibold">Anomaly timeline</h2>
        <div className="flex gap-1 rounded-md border border-slate-800 bg-slate-900/60 p-0.5">
          {WINDOW_OPTIONS.map((o) => (
            <button
              key={o.value}
              onClick={() => setWindow(o.value)}
              className={classes(
                "rounded px-2 py-0.5 text-xs",
                window === o.value
                  ? "bg-slate-700 text-slate-100"
                  : "text-slate-400 hover:text-slate-200",
              )}
            >
              {o.label}
            </button>
          ))}
        </div>
      </div>
      <div style={{ width: "100%", height: 240 }}>
        <ResponsiveContainer>
          <AreaChart data={data} margin={{ top: 4, right: 8, left: -12, bottom: 0 }}>
            <defs>
              {[
                { id: "critGrad", color: "#ef4444" },
                { id: "warnGrad", color: "#f59e0b" },
                { id: "infoGrad", color: "#3b82f6" },
              ].map((g) => (
                <linearGradient key={g.id} id={g.id} x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor={g.color} stopOpacity={0.6} />
                  <stop offset="100%" stopColor={g.color} stopOpacity={0} />
                </linearGradient>
              ))}
            </defs>
            <CartesianGrid stroke="#1e293b" strokeDasharray="3 3" />
            <XAxis
              dataKey="ts"
              type="number"
              domain={["dataMin", "dataMax"]}
              tickFormatter={(t: number) =>
                new Date(t).toLocaleTimeString(undefined, {
                  hour: "2-digit",
                  minute: "2-digit",
                })
              }
              stroke="#475569"
              tick={{ fontSize: 11, fill: "#94a3b8" }}
            />
            <YAxis stroke="#475569" tick={{ fontSize: 11, fill: "#94a3b8" }} />
            <Tooltip
              contentStyle={{
                background: "#0f172a",
                border: "1px solid #334155",
                borderRadius: 6,
                fontSize: 12,
              }}
              labelFormatter={(t: number) => new Date(t).toLocaleString()}
            />
            <Area
              type="monotone"
              dataKey="info"
              stackId="1"
              stroke="#3b82f6"
              fill="url(#infoGrad)"
            />
            <Area
              type="monotone"
              dataKey="warning"
              stackId="1"
              stroke="#f59e0b"
              fill="url(#warnGrad)"
            />
            <Area
              type="monotone"
              dataKey="critical"
              stackId="1"
              stroke="#ef4444"
              fill="url(#critGrad)"
            />
          </AreaChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
