"use client";

import * as React from "react";

export type QueryState<T> =
  | { status: "loading"; data: undefined; error: undefined; refreshing: false }
  | { status: "success"; data: T; error: undefined; refreshing: boolean }
  | { status: "error"; data: T | undefined; error: unknown; refreshing: false };

/**
 * One load of one thing, kept outside React state so that components only subscribe to it.
 * A reload keeps showing the previous data (`refreshing`) instead of flashing a spinner.
 */
class Query<T> {
  private state: QueryState<T> = {
    status: "loading",
    data: undefined,
    error: undefined,
    refreshing: false,
  };
  private listeners = new Set<() => void>();
  private run = 0;
  private active = false;

  constructor(private readonly fetcher: (signal: AbortSignal) => Promise<T>) {}

  subscribe = (listener: () => void) => {
    this.listeners.add(listener);
    return () => void this.listeners.delete(listener);
  };

  getSnapshot = () => this.state;

  private set(next: QueryState<T>) {
    this.state = next;
    for (const l of this.listeners) l();
  }

  start() {
    this.active = true;
    void this.load();
  }

  stop() {
    this.active = false;
    this.run += 1; // anything still in flight is ignored
  }

  reload = () => this.load();

  private async load() {
    const id = ++this.run;
    const previous = this.state.data;
    if (previous !== undefined) {
      this.set({ status: "success", data: previous, error: undefined, refreshing: true });
    } else if (this.state.status !== "loading") {
      this.set({ status: "loading", data: undefined, error: undefined, refreshing: false });
    }
    const controller = new AbortController();
    try {
      const data = await this.fetcher(controller.signal);
      if (this.active && id === this.run)
        this.set({ status: "success", data, error: undefined, refreshing: false });
    } catch (error) {
      if (this.active && id === this.run)
        this.set({ status: "error", data: previous, error, refreshing: false });
    }
  }
}

export interface QueryResult<T> {
  state: QueryState<T>;
  reload: () => Promise<void>;
}

/**
 * Loads data when the component mounts and whenever `key` changes. `fetcher` should only depend
 * on what is in `key`.
 */
export function useQuery<T>(
  key: string,
  fetcher: (signal: AbortSignal) => Promise<T>,
): QueryResult<T> {
  // A new Query per key; `fetcher` is read once, which is why it may only depend on the key.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const query = React.useMemo(() => new Query<T>(fetcher), [key]);
  React.useEffect(() => {
    query.start();
    return () => query.stop();
  }, [query]);
  const state = React.useSyncExternalStore(query.subscribe, query.getSnapshot, query.getSnapshot);
  return { state, reload: query.reload };
}
