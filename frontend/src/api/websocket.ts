/**
 * Single shared WebSocket connection to /api/v1/ws/anomalies.
 *
 * Reconnect with exponential backoff per the contract
 * (docs/architecture/api_contract.md "Server messages").
 * Heartbeat ping frames are silently dropped; "anomaly" and
 * "explanation_ready" frames are dispatched to subscribers.
 */
import type { WsMessage } from "./types";

type Listener = (msg: WsMessage) => void;
type StatusListener = (s: ConnectionStatus) => void;

export type ConnectionStatus = "connecting" | "open" | "reconnecting" | "closed";

const WS_URL = `${location.protocol === "https:" ? "wss:" : "ws:"}//${
  location.host
}/api/v1/ws/anomalies`;

class WsClient {
  private socket: WebSocket | null = null;
  private listeners = new Set<Listener>();
  private statusListeners = new Set<StatusListener>();
  private status: ConnectionStatus = "closed";
  private reconnectAttempts = 0;
  private reconnectTimer: number | null = null;
  private intentionallyClosed = false;

  connect() {
    if (this.socket && this.socket.readyState !== WebSocket.CLOSED) return;
    this.intentionallyClosed = false;
    this.setStatus(this.reconnectAttempts > 0 ? "reconnecting" : "connecting");
    this.socket = new WebSocket(WS_URL);

    this.socket.addEventListener("open", () => {
      this.reconnectAttempts = 0;
      this.setStatus("open");
    });

    this.socket.addEventListener("message", (ev) => {
      try {
        const msg = JSON.parse(ev.data) as WsMessage;
        // ping is just a heartbeat; ignore.
        if (msg.type === "ping") return;
        for (const fn of this.listeners) fn(msg);
      } catch {
        // ignore malformed frames
      }
    });

    this.socket.addEventListener("close", () => {
      this.socket = null;
      if (this.intentionallyClosed) {
        this.setStatus("closed");
        return;
      }
      this.scheduleReconnect();
    });

    this.socket.addEventListener("error", () => {
      // The "close" handler will fire next and trigger reconnect; nothing to do here.
    });
  }

  disconnect() {
    this.intentionallyClosed = true;
    if (this.reconnectTimer !== null) {
      window.clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    this.socket?.close();
    this.socket = null;
    this.setStatus("closed");
  }

  subscribe(fn: Listener): () => void {
    this.listeners.add(fn);
    return () => this.listeners.delete(fn);
  }

  onStatus(fn: StatusListener): () => void {
    this.statusListeners.add(fn);
    fn(this.status); // emit current status immediately
    return () => this.statusListeners.delete(fn);
  }

  private scheduleReconnect() {
    this.setStatus("reconnecting");
    const backoff = Math.min(1000 * 2 ** this.reconnectAttempts, 30_000);
    this.reconnectAttempts += 1;
    this.reconnectTimer = window.setTimeout(() => {
      this.reconnectTimer = null;
      this.connect();
    }, backoff);
  }

  private setStatus(s: ConnectionStatus) {
    this.status = s;
    for (const fn of this.statusListeners) fn(s);
  }
}

export const wsClient = new WsClient();
