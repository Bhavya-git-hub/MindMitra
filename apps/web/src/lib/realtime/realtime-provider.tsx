"use client";

import * as React from "react";

import { API_PREFIX } from "@/lib/api/client";
import { useAuth } from "@/lib/auth/auth-context";
import { apiBaseUrl } from "@/lib/env";

import type { RealtimeEvent } from "./events";
import { RealtimeClient, type SocketLike } from "./realtime-client";

type Subscribe = (listener: (event: RealtimeEvent) => void) => () => void;

const RealtimeContext = React.createContext<Subscribe | null>(null);

/** Coming back to the tab refreshes what is on screen, at most this often. */
const RESYNC_GAP_MS = 5_000;

export function realtimeUrl(base: string = apiBaseUrl()): string {
  return `${base.replace(/^http/, "ws")}${API_PREFIX}/ws`;
}

/**
 * Keeps one real-time connection open while someone is signed in, and lets any view below it
 * listen with `useRealtimeEvent`. Views still load everything through the API; events only tell
 * them when to load again.
 */
export function RealtimeProvider({
  children,
  createSocket,
  url,
}: {
  children: React.ReactNode;
  /** Injected in tests. */
  createSocket?: (url: string) => SocketLike;
  url?: string;
}) {
  const { status, manager } = useAuth();
  const listeners = React.useRef(new Set<(event: RealtimeEvent) => void>());

  const emit = React.useCallback((event: RealtimeEvent) => {
    for (const listener of [...listeners.current]) listener(event);
  }, []);

  React.useEffect(() => {
    if (status !== "authenticated") return;
    if (!createSocket && typeof WebSocket === "undefined") return;
    const client = new RealtimeClient({
      url: url ?? realtimeUrl(),
      getToken: () => manager.getAccessToken(),
      refresh: () => manager.refresh(),
      createSocket,
    });
    const off = client.subscribe(emit);
    client.start();
    return () => {
      off();
      client.stop();
    };
  }, [status, manager, createSocket, url, emit]);

  React.useEffect(() => {
    if (status !== "authenticated") return;
    let last = 0;
    function onVisible() {
      if (document.visibilityState !== "visible") return;
      const now = Date.now();
      if (now - last < RESYNC_GAP_MS) return;
      last = now;
      emit({ type: "resync" });
    }
    document.addEventListener("visibilitychange", onVisible);
    return () => document.removeEventListener("visibilitychange", onVisible);
  }, [status, emit]);

  const subscribe = React.useCallback<Subscribe>((listener) => {
    listeners.current.add(listener);
    return () => void listeners.current.delete(listener);
  }, []);

  return <RealtimeContext.Provider value={subscribe}>{children}</RealtimeContext.Provider>;
}

/**
 * Calls `handler` for every real-time event (including `resync`). Outside a provider it does
 * nothing, so views work the same without a live connection; they just refresh less often.
 */
export function useRealtimeEvent(handler: (event: RealtimeEvent) => void): void {
  const subscribe = React.useContext(RealtimeContext);
  const latest = React.useRef(handler);
  React.useEffect(() => {
    latest.current = handler;
  });
  React.useEffect(() => {
    if (!subscribe) return;
    return subscribe((event) => latest.current(event));
  }, [subscribe]);
}
