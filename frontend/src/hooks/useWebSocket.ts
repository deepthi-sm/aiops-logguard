/**
 * `useWebSocket()` — React glue around the singleton `wsClient`.
 *
 * Mount this once near the root of the authenticated app (Layout). It:
 *   1. Calls `wsClient.connect()` on mount, `disconnect()` on unmount.
 *   2. On every "anomaly" frame, invalidates the TanStack-Query caches
 *      that depend on the anomaly list (`anomalies`, `metrics-summary`,
 *      `timeline`) so the dashboard refreshes immediately.
 *   3. On every "explanation_ready" frame, invalidates the matching
 *      `explanation` query so a pending detail page swaps to the ready
 *      explanation without polling further.
 *   4. Exposes `status` + `eventsPerSecond` so the sidebar pill shows a
 *      live connection indicator with rolling rate.
 *
 * Returns:
 *   - `status`: current ConnectionStatus, re-rendered on change.
 *   - `eventsPerSecond`: rolling 60 s rate, re-rendered ~once a second.
 */
import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import {
  wsClient,
  type ConnectionStatus,
} from "../api/websocket";

interface UseWebSocketResult {
  status: ConnectionStatus;
  eventsPerSecond: number;
}

export function useWebSocket(): UseWebSocketResult {
  const qc = useQueryClient();
  const [status, setStatus] = useState<ConnectionStatus>(() => wsClient.status());
  const [eventsPerSecond, setEventsPerSecond] = useState<number>(0);

  // Mount: open socket, subscribe to status, dispatch frames into the cache.
  useEffect(() => {
    const unsubscribeStatus = wsClient.onStatus(setStatus);
    const unsubscribeMessages = wsClient.subscribe((msg) => {
      switch (msg.type) {
        case "anomaly": {
          // List, metrics, and timeline all reflect the new anomaly.
          // Detail page (`anomaly`, id) is keyed per id and will refetch
          // on next mount; we don't preemptively prime it here because
          // the list refetch will hand it back fresh.
          qc.invalidateQueries({ queryKey: ["anomalies"] });
          qc.invalidateQueries({ queryKey: ["metrics-summary"] });
          qc.invalidateQueries({ queryKey: ["timeline"] });
          break;
        }
        case "explanation_ready": {
          qc.invalidateQueries({
            queryKey: ["explanation", msg.data.anomaly_id],
          });
          // Status field on the anomaly detail row also flips.
          qc.invalidateQueries({
            queryKey: ["anomaly", msg.data.anomaly_id],
          });
          break;
        }
        case "ping":
          // Server-side keepalive — no UI effect.
          break;
        default: {
          // Exhaustiveness sentinel — TS narrows `msg` to `never` here.
          const _exhaustive: never = msg;
          void _exhaustive;
        }
      }
    });
    wsClient.connect();
    return () => {
      unsubscribeStatus();
      unsubscribeMessages();
      // We don't `disconnect()` on unmount: HMR re-renders would close
      // and reopen the socket on every code change. The singleton lives
      // for the lifetime of the page; tab close ends the session.
    };
  }, [qc]);

  // Poll the rolling rate once a second. Cheap — single arithmetic op +
  // a setState only when the displayed integer changes.
  useEffect(() => {
    const id = window.setInterval(() => {
      const next = wsClient.eventsPerSecond();
      setEventsPerSecond((prev) => (Math.abs(prev - next) < 1e-6 ? prev : next));
    }, 1_000);
    return () => window.clearInterval(id);
  }, []);

  return { status, eventsPerSecond };
}
