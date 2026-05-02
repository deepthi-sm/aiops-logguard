/**
 * Real WebSocket client for `/api/v1/ws/anomalies`.
 *
 * Frames the backend can send (per `backend/api/ws.py`):
 *   - { type: "anomaly", data: Anomaly }                — new anomaly detected
 *   - { type: "explanation_ready", data: {...} }        — RAG worker finished
 *   - { type: "ping" }                                  — server heartbeat (~30 s)
 *
 * Behaviour:
 *   - Auto-reconnect with exponential backoff (1 s → 30 s cap, ±30 % jitter).
 *   - Idempotent `connect()` — safe to call from multiple mount points.
 *   - `disconnect()` closes cleanly and prevents the next reconnect attempt.
 *   - Tracks a 60 s rolling window of "anomaly"-frame timestamps so the
 *     sidebar status pill can show events/sec without polling.
 *
 * Subscribers see decoded `WsMessage` envelopes; malformed frames are
 * dropped with a console warning so a stray ping from a buggy backend
 * can't break the dashboard.
 *
 * The dev server proxies `/api` (including the WS upgrade) to the
 * backend on :8000 — see `vite.config.ts`. In production the same path
 * works because the API and the static frontend are served from the
 * same origin.
 */
import type { WsMessage } from "../types";

export type ConnectionStatus =
  | "connecting"
  | "connected"
  | "disconnected"
  | "reconnecting";

export interface WsClient {
  /** Open the connection (idempotent). */
  connect(): void;
  /** Close cleanly (intentional disconnect — won't auto-reconnect). */
  disconnect(): void;
  /** Subscribe to incoming server frames. Returns an unsubscribe fn. */
  subscribe(fn: (msg: WsMessage) => void): () => void;
  /** Subscribe to connection-status changes. Returns an unsubscribe fn. */
  onStatus(fn: (s: ConnectionStatus) => void): () => void;
  /** Current connection status — synchronous read for new subscribers. */
  status(): ConnectionStatus;
  /** Rolling 60 s anomaly-frame rate (events / second). */
  eventsPerSecond(): number;
}

// -- backoff + rate config ------------------------------------------------

const RECONNECT_BASE_MS = 1_000;
const RECONNECT_MAX_MS = 30_000;
const JITTER_FRACTION = 0.3;
const RATE_WINDOW_MS = 60_000;

function wsUrl(): string {
  // Same-origin: dev server proxies /api/v1/ws/anomalies → backend:8000
  // (see frontend/vite.config.ts). Prod: same origin serves both, so the
  // path works without extra config.
  if (typeof window === "undefined") return "";
  const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${proto}//${window.location.host}/api/v1/ws/anomalies`;
}

function backoffDelay(attempt: number): number {
  // attempt is 1-indexed: 1s, 2s, 4s, 8s, 16s, then capped at 30s.
  const base = Math.min(
    RECONNECT_MAX_MS,
    RECONNECT_BASE_MS * 2 ** Math.max(0, attempt - 1),
  );
  const jitter = base * JITTER_FRACTION * (Math.random() * 2 - 1);
  return Math.max(RECONNECT_BASE_MS, Math.round(base + jitter));
}

// -- implementation -------------------------------------------------------

class RealWsClient implements WsClient {
  private socket: WebSocket | null = null;
  private _status: ConnectionStatus = "disconnected";
  private subscribers = new Set<(msg: WsMessage) => void>();
  private statusSubscribers = new Set<(s: ConnectionStatus) => void>();
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private reconnectAttempts = 0;
  /** Rolling timestamps (ms) of "anomaly" frames within the last 60 s. */
  private anomalyTimestamps: number[] = [];
  /** When true, `disconnect()` was called — don't reconnect on close. */
  private intentionallyClosed = false;

  connect(): void {
    if (typeof window === "undefined") return;
    if (this.socket && this.socket.readyState !== WebSocket.CLOSED) {
      return; // already connecting / open
    }
    this.intentionallyClosed = false;
    this.openSocket();
  }

  disconnect(): void {
    this.intentionallyClosed = true;
    this.clearReconnectTimer();
    if (this.socket) {
      try {
        this.socket.close();
      } catch {
        /* swallow — already closed */
      }
      this.socket = null;
    }
    this.setStatus("disconnected");
  }

  subscribe(fn: (msg: WsMessage) => void): () => void {
    this.subscribers.add(fn);
    return () => {
      this.subscribers.delete(fn);
    };
  }

  onStatus(fn: (s: ConnectionStatus) => void): () => void {
    this.statusSubscribers.add(fn);
    // Emit current status immediately so callers don't need to also call
    // `status()` separately to render the initial state.
    queueMicrotask(() => fn(this._status));
    return () => {
      this.statusSubscribers.delete(fn);
    };
  }

  status(): ConnectionStatus {
    return this._status;
  }

  eventsPerSecond(): number {
    this.pruneRateWindow();
    return this.anomalyTimestamps.length / (RATE_WINDOW_MS / 1000);
  }

  // -- internals ----------------------------------------------------------

  private openSocket(): void {
    const url = wsUrl();
    if (!url) return;
    this.setStatus(
      this.reconnectAttempts > 0 ? "reconnecting" : "connecting",
    );
    let socket: WebSocket;
    try {
      socket = new WebSocket(url);
    } catch (err) {
      // Synchronous construction error (rare — bad URL, blocked by CSP).
      // eslint-disable-next-line no-console
      console.warn("[ws] failed to construct WebSocket:", err);
      this.scheduleReconnect();
      return;
    }
    this.socket = socket;

    socket.onopen = () => {
      this.reconnectAttempts = 0;
      this.setStatus("connected");
    };

    socket.onmessage = (event) => {
      this.handleFrame(event.data);
    };

    socket.onerror = () => {
      // Browsers don't surface the underlying reason. The `onclose` that
      // follows will trigger the reconnect path.
    };

    socket.onclose = () => {
      this.socket = null;
      if (this.intentionallyClosed) {
        this.setStatus("disconnected");
        return;
      }
      this.scheduleReconnect();
    };
  }

  private handleFrame(raw: unknown): void {
    if (typeof raw !== "string") return; // we don't send binary frames
    let parsed: unknown;
    try {
      parsed = JSON.parse(raw);
    } catch {
      // eslint-disable-next-line no-console
      console.warn("[ws] dropping non-JSON frame");
      return;
    }
    if (!isWsMessage(parsed)) {
      // eslint-disable-next-line no-console
      console.warn("[ws] dropping unknown frame:", parsed);
      return;
    }
    if (parsed.type === "anomaly") {
      this.recordAnomaly();
    }
    for (const fn of this.subscribers) {
      try {
        fn(parsed);
      } catch (err) {
        // A bad subscriber must not break the loop for the others.
        // eslint-disable-next-line no-console
        console.error("[ws] subscriber threw:", err);
      }
    }
  }

  private recordAnomaly(): void {
    const now = Date.now();
    this.anomalyTimestamps.push(now);
    this.pruneRateWindow(now);
  }

  private pruneRateWindow(now: number = Date.now()): void {
    const cutoff = now - RATE_WINDOW_MS;
    // Timestamps are pushed in order, so a leading slice is enough.
    let i = 0;
    while (i < this.anomalyTimestamps.length && this.anomalyTimestamps[i] < cutoff) {
      i += 1;
    }
    if (i > 0) this.anomalyTimestamps.splice(0, i);
  }

  private scheduleReconnect(): void {
    this.clearReconnectTimer();
    this.reconnectAttempts += 1;
    const delay = backoffDelay(this.reconnectAttempts);
    this.setStatus("reconnecting");
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      this.openSocket();
    }, delay);
  }

  private clearReconnectTimer(): void {
    if (this.reconnectTimer !== null) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
  }

  private setStatus(s: ConnectionStatus): void {
    if (this._status === s) return;
    this._status = s;
    for (const fn of this.statusSubscribers) {
      try {
        fn(s);
      } catch (err) {
        // eslint-disable-next-line no-console
        console.error("[ws] status subscriber threw:", err);
      }
    }
  }
}

// -- type guard -----------------------------------------------------------

function isWsMessage(value: unknown): value is WsMessage {
  if (!value || typeof value !== "object") return false;
  const t = (value as { type?: unknown }).type;
  if (t === "ping") return true;
  if (t === "anomaly" || t === "explanation_ready") {
    return "data" in value && typeof (value as { data: unknown }).data === "object";
  }
  return false;
}

// Singleton — every component imports the same instance, so multiple
// mounts don't open extra sockets. `connect()` is idempotent.
export const wsClient: WsClient = new RealWsClient();
