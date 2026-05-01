/**
 * WebSocket client — placeholder for Step 9.
 *
 * Step 3 ships only the type definitions and a no-op default export so
 * other modules can import `wsClient` and `ConnectionStatus` without
 * needing the implementation yet. Step 9 fills this in: connect to
 * `/api/v1/ws/anomalies`, exponential-backoff reconnect, expose a
 * `subscribe()` API for "anomaly" / "explanation_ready" / "ping" frames,
 * track a rolling event-rate, etc.
 */
import type { WsMessage } from "../types";

export type ConnectionStatus =
  | "connecting"
  | "connected"
  | "disconnected"
  | "reconnecting";

export interface WsClient {
  /** Open the connection (idempotent). No-op until Step 9. */
  connect(): void;
  /** Close cleanly (intentional disconnect). */
  disconnect(): void;
  /** Subscribe to incoming server frames. Returns an unsubscribe fn. */
  subscribe(fn: (msg: WsMessage) => void): () => void;
  /** Subscribe to connection-status changes. Returns an unsubscribe fn. */
  onStatus(fn: (s: ConnectionStatus) => void): () => void;
}

const NOOP_UNSUBSCRIBE = () => undefined;

export const wsClient: WsClient = {
  connect: () => undefined,
  disconnect: () => undefined,
  subscribe: () => NOOP_UNSUBSCRIBE,
  onStatus: (fn) => {
    // Keep the sidebar/status UI happy: emit a synthetic "connected"
    // immediately so the green pulsing dot appears even before Step 9.
    queueMicrotask(() => fn("connected"));
    return NOOP_UNSUBSCRIBE;
  },
};
