/**
 * Bridges the WebSocket stream to TanStack Query's cache.
 *
 * On every "anomaly" frame: prepend it to the cached list so the dashboard
 * updates without a poll. On "explanation_ready": invalidate the explanation
 * query so the detail panel re-fetches and shows the freshly generated text.
 */
import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { wsClient, type ConnectionStatus } from "../api/websocket";
import type { AnomalyListResponse } from "../api/types";

export function useLiveAnomalies() {
  const qc = useQueryClient();
  const [status, setStatus] = useState<ConnectionStatus>("connecting");

  useEffect(() => {
    wsClient.connect();
    const unsubMsg = wsClient.subscribe((msg) => {
      if (msg.type === "anomaly") {
        // Prepend to every "anomalies" cache page so the live feed reflects
        // the new event immediately. The 5-second poll backstops any drops.
        qc.setQueriesData<AnomalyListResponse>(
          { queryKey: ["anomalies"] },
          (old) => {
            if (!old) return old;
            // De-dupe by id in case the poll already inserted it.
            if (old.items.some((a) => a.id === msg.data.id)) return old;
            return { ...old, items: [msg.data, ...old.items].slice(0, 200) };
          },
        );
        // Bump KPI cards too so the user sees counts move in real time.
        qc.invalidateQueries({ queryKey: ["metrics-summary"] });
      } else if (msg.type === "explanation_ready") {
        qc.invalidateQueries({
          queryKey: ["explanation", msg.data.anomaly_id],
        });
      }
    });
    const unsubStatus = wsClient.onStatus(setStatus);
    return () => {
      unsubMsg();
      unsubStatus();
    };
  }, [qc]);

  return { status };
}
