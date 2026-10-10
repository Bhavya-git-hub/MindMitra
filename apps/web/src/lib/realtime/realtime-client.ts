/**
 * One WebSocket to the API per tab, for real-time hints (ADR 0009).
 *
 * - The access token goes in the first frame, never in the URL, so it stays out of logs.
 * - The socket reconnects with capped, jittered backoff. After a reconnect it emits `resync`,
 *   because events sent while it was away are not replayed.
 * - A 4401 close means the token expired or the session ended: it refreshes once through the
 *   session manager and reconnects, or stops if the session is over. A 4403 (origin refused)
 *   stops for good; retrying cannot fix it.
 */
import { parseEvent, type RealtimeEvent } from "./events";

/** The parts of the browser `WebSocket` this client uses (tests pass a fake). */
export interface SocketLike {
  send(data: string): void;
  close(code?: number): void;
  onopen: ((event: Event) => void) | null;
  onmessage: ((event: MessageEvent) => void) | null;
  onclose: ((event: CloseEvent) => void) | null;
  onerror: ((event: Event) => void) | null;
}

export type RealtimeStatus = "idle" | "connecting" | "open" | "stopped";

export interface RealtimeClientOptions {
  url: string;
  getToken: () => string | null;
  /** Gets a fresh access token; resolves false when the session is over. */
  refresh: () => Promise<boolean>;
  createSocket?: (url: string) => SocketLike;
  /** Overridable for tests. */
  random?: () => number;
}

export const CLOSE_UNAUTHENTICATED = 4401;
export const CLOSE_ORIGIN = 4403;
const PING_EVERY_MS = 25_000;
const BASE_DELAY_MS = 1_000;
const MAX_DELAY_MS = 30_000;

export function reconnectDelay(attempt: number, random: () => number = Math.random): number {
  const capped = Math.min(MAX_DELAY_MS, BASE_DELAY_MS * 2 ** attempt);
  return Math.round(capped / 2 + (random() * capped) / 2);
}

export class RealtimeClient {
  private socket: SocketLike | null = null;
  private status: RealtimeStatus = "idle";
  private attempt = 0;
  private everOpened = false;
  private refreshedForThisSocket = false;
  private retryTimer: ReturnType<typeof setTimeout> | null = null;
  private pingTimer: ReturnType<typeof setInterval> | null = null;
  private readonly listeners = new Set<(event: RealtimeEvent) => void>();

  constructor(private readonly options: RealtimeClientOptions) {}

  getStatus(): RealtimeStatus {
    return this.status;
  }

  subscribe(listener: (event: RealtimeEvent) => void): () => void {
    this.listeners.add(listener);
    return () => void this.listeners.delete(listener);
  }

  emit(event: RealtimeEvent): void {
    for (const listener of [...this.listeners]) {
      try {
        listener(event);
      } catch {
        // One view's handler must not stop the others from hearing the event.
      }
    }
  }

  start(): void {
    if (this.status !== "idle") return;
    this.connect();
  }

  stop(): void {
    this.status = "stopped";
    this.clearTimers();
    const socket = this.socket;
    this.socket = null;
    if (socket) {
      socket.onclose = null;
      socket.onmessage = null;
      socket.onerror = null;
      socket.onopen = null;
      try {
        socket.close(1000);
      } catch {
        // Already closed.
      }
    }
  }

  private connect(): void {
    if (this.status === "stopped") return;
    const token = this.options.getToken();
    if (!token) {
      this.scheduleRetry();
      return;
    }
    this.status = "connecting";
    const create = this.options.createSocket ?? ((url: string) => new WebSocket(url));
    let socket: SocketLike;
    try {
      socket = create(this.options.url);
    } catch {
      this.scheduleRetry();
      return;
    }
    this.socket = socket;
    socket.onopen = () => socket.send(JSON.stringify({ type: "auth", token }));
    socket.onmessage = (event) => this.onFrame(event.data);
    socket.onerror = () => undefined; // a close always follows
    socket.onclose = (event) => void this.onClose(socket, event.code);
  }

  private onFrame(data: unknown): void {
    if (typeof data !== "string") return;
    let frame: unknown;
    try {
      frame = JSON.parse(data);
    } catch {
      return;
    }
    if ((frame as { type?: unknown } | null)?.type === "ready") {
      this.onReady();
      return;
    }
    const event = parseEvent(frame);
    if (event) this.emit(event);
  }

  private onReady(): void {
    this.status = "open";
    this.attempt = 0;
    this.refreshedForThisSocket = false;
    if (this.everOpened) this.emit({ type: "resync" });
    this.everOpened = true;
    this.pingTimer = setInterval(() => {
      try {
        this.socket?.send(JSON.stringify({ type: "ping" }));
      } catch {
        // The close handler reconnects.
      }
    }, PING_EVERY_MS);
  }

  private async onClose(socket: SocketLike, code: number): Promise<void> {
    if (socket !== this.socket || this.status === "stopped") return;
    this.socket = null;
    this.clearTimers();
    if (code === CLOSE_ORIGIN) {
      this.status = "stopped";
      return;
    }
    if (code === CLOSE_UNAUTHENTICATED) {
      if (this.refreshedForThisSocket) {
        this.scheduleRetry();
        return;
      }
      this.refreshedForThisSocket = true;
      const ok = await this.options.refresh().catch(() => false);
      if (this.isStopped()) return; // stop() may have run while refreshing
      if (!ok) {
        this.status = "stopped"; // signed out: nothing to listen for
        return;
      }
      this.status = "idle";
      this.connect();
      return;
    }
    this.scheduleRetry();
  }

  private isStopped(): boolean {
    return this.status === "stopped";
  }

  private scheduleRetry(): void {
    if (this.status === "stopped") return;
    this.status = "idle";
    const delay = reconnectDelay(this.attempt, this.options.random);
    this.attempt += 1;
    this.retryTimer = setTimeout(() => {
      this.retryTimer = null;
      this.connect();
    }, delay);
  }

  private clearTimers(): void {
    if (this.retryTimer) clearTimeout(this.retryTimer);
    if (this.pingTimer) clearInterval(this.pingTimer);
    this.retryTimer = null;
    this.pingTimer = null;
  }
}
