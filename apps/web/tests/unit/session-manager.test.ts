import { describe, expect, it, vi } from "vitest";

import { CSRF_STORAGE_KEY, SessionManager } from "@/lib/auth/session-manager";

import { API, fakeApi, json, me, problem, tokens } from "../helpers/api";

type Handlers = Parameters<typeof fakeApi>[0];

function setup(handlers: Handlers, opts: { csrf?: string } = {}) {
  const api = fakeApi(handlers);
  const store = new Map<string, string>(opts.csrf ? [[CSRF_STORAGE_KEY, opts.csrf]] : []);
  const storage = {
    getItem: (k: string) => store.get(k) ?? null,
    setItem: (k: string, v: string) => void store.set(k, v),
    removeItem: (k: string) => void store.delete(k),
  };
  const syncPass = vi.fn(async () => {});
  const channels: {
    onmessage: ((e: MessageEvent) => void) | null;
    postMessage: ReturnType<typeof vi.fn>;
    close: () => void;
  }[] = [];
  const manager = new SessionManager({
    fetchImpl: api.fetch,
    baseUrl: () => API,
    storage,
    locks: null,
    syncPass,
    createChannel: () => {
      const ch = { onmessage: null, postMessage: vi.fn(), close: () => {} };
      channels.push(ch);
      return ch;
    },
  });
  return { manager, store, syncPass, channels, ...api };
}

describe("SessionManager.login", () => {
  it("stores the CSRF token, keeps the access token in memory, and sets the portal pass", async () => {
    const { manager, store, syncPass, calls } = setup({
      "POST /auth/login": () => json(tokens("therapist")),
      "GET /me": () => json(me("therapist")),
    });

    const user = await manager.login({ email: "a@test.example", password: "pw" });

    expect(user.role).toBe("therapist");
    expect(manager.getState()).toMatchObject({
      status: "authenticated",
      user: { role: "therapist" },
    });
    expect(manager.getAccessToken()).toBe("access-1");
    expect(store.get(CSRF_STORAGE_KEY)).toBe("csrf-1");
    expect(syncPass).toHaveBeenCalledWith("access-1");
    expect(calls.find((c) => c.path === "/me")?.headers.get("Authorization")).toBe(
      "Bearer access-1",
    );
    // Nothing secret ever lands in storage except the CSRF token.
    expect([...store.keys()]).toEqual([CSRF_STORAGE_KEY]);
    expect(JSON.stringify([...store.values()])).not.toContain("access-1");
  });

  it("surfaces bad credentials as an ApiError and stays signed out", async () => {
    const { manager, store } = setup({
      "POST /auth/login": () => problem(401, "Invalid email or password."),
    });
    await expect(manager.login({ email: "a@test.example", password: "x" })).rejects.toMatchObject({
      status: 401,
    });
    expect(manager.getAccessToken()).toBeNull();
    expect(store.size).toBe(0);
  });

  it("ends the session if the profile cannot be loaded", async () => {
    const { manager, store, syncPass } = setup({
      "POST /auth/login": () => json(tokens()),
      "GET /me": () => problem(500, "boom"),
    });
    await expect(manager.login({ email: "a@test.example", password: "pw" })).rejects.toBeTruthy();
    expect(manager.getState().status).toBe("unauthenticated");
    expect(manager.getAccessToken()).toBeNull();
    expect(store.size).toBe(0);
    expect(syncPass).toHaveBeenLastCalledWith(null);
  });
});

describe("SessionManager.bootstrap", () => {
  it("restores a session after reload using the stored CSRF token", async () => {
    const { manager, store, calls } = setup(
      {
        "POST /auth/refresh": () => json(tokens("teacher", 2)),
        "GET /me": () => json(me("teacher")),
      },
      { csrf: "csrf-1" },
    );
    await manager.bootstrap();
    expect(calls[0]?.headers.get("X-CSRF-Token")).toBe("csrf-1");
    expect(manager.getState()).toMatchObject({
      status: "authenticated",
      user: { role: "teacher" },
    });
    expect(store.get(CSRF_STORAGE_KEY)).toBe("csrf-2"); // rotated
  });

  it("is signed out, and clears any stale pass, when there is no CSRF token", async () => {
    const { manager, syncPass, mock } = setup({});
    await manager.bootstrap();
    expect(manager.getState().status).toBe("unauthenticated");
    expect(syncPass).toHaveBeenCalledWith(null);
    expect(mock).not.toHaveBeenCalled();
  });

  it("ends the session when the server rejects the refresh", async () => {
    const { manager, store, syncPass } = setup(
      { "POST /auth/refresh": () => problem(401, "Invalid token") },
      { csrf: "csrf-1" },
    );
    await manager.bootstrap();
    expect(manager.getState().status).toBe("unauthenticated");
    expect(store.size).toBe(0);
    expect(syncPass).toHaveBeenCalledWith(null);
  });

  it("keeps the CSRF token when the server is merely unreachable", async () => {
    const { manager, store } = setup(
      { "POST /auth/refresh": () => problem(503, "down") },
      { csrf: "csrf-1" },
    );
    await manager.bootstrap();
    expect(manager.getState().status).toBe("unauthenticated");
    expect(store.get(CSRF_STORAGE_KEY)).toBe("csrf-1");
  });

  it("runs once even when called twice (React StrictMode)", async () => {
    const { manager, mock } = setup(
      {
        "POST /auth/refresh": () => json(tokens("student", 2)),
        "GET /me": () => json(me()),
      },
      { csrf: "csrf-1" },
    );
    await Promise.all([manager.bootstrap(), manager.bootstrap()]);
    expect(mock.mock.calls.filter(([url]) => String(url).endsWith("/auth/refresh"))).toHaveLength(
      1,
    );
  });
});

describe("SessionManager token refresh", () => {
  async function signedIn(extra: Handlers = {}) {
    const ctx = setup({
      "POST /auth/login": () => json(tokens("student", 1)),
      "GET /me": () => json(me()),
      ...extra,
    });
    await ctx.manager.login({ email: "a@test.example", password: "pw" });
    return ctx;
  }

  it("refreshes after a 401 and retries the request with the new token", async () => {
    let refreshes = 0;
    const { manager, store } = await signedIn({
      "POST /auth/refresh": () => json(tokens("student", 2 + refreshes++)),
      "GET /me/mood": ({ headers }) =>
        headers.get("Authorization") === "Bearer access-2"
          ? json({ ok: true })
          : problem(401, "expired"),
    });
    const result = await manager.api.request("/me/mood");
    expect(result).toBeUndefined(); // no schema
    expect(refreshes).toBe(1);
    expect(manager.getAccessToken()).toBe("access-2");
    expect(store.get(CSRF_STORAGE_KEY)).toBe("csrf-2");
  });

  it("shares one refresh between parallel requests (refresh tokens are single use)", async () => {
    let refreshes = 0;
    const { manager } = await signedIn({
      "POST /auth/refresh": async () => {
        refreshes += 1;
        await new Promise((r) => setTimeout(r, 10));
        return json(tokens("student", 2));
      },
      "GET /a": ({ headers }) =>
        headers.get("Authorization") === "Bearer access-2" ? json({}) : problem(401, "x"),
      "GET /b": ({ headers }) =>
        headers.get("Authorization") === "Bearer access-2" ? json({}) : problem(401, "x"),
      "GET /c": ({ headers }) =>
        headers.get("Authorization") === "Bearer access-2" ? json({}) : problem(401, "x"),
    });
    await Promise.all(["/a", "/b", "/c"].map((p) => manager.api.request(p)));
    expect(refreshes).toBe(1);
  });

  it("signs the user out when the refresh is rejected (for example reuse detected)", async () => {
    const { manager, store, syncPass } = await signedIn({
      "POST /auth/refresh": () => problem(401, "Invalid token"),
      "GET /me/mood": () => problem(401, "expired"),
    });
    await expect(manager.api.request("/me/mood")).rejects.toMatchObject({ status: 401 });
    expect(manager.getState().status).toBe("unauthenticated");
    expect(manager.getAccessToken()).toBeNull();
    expect(store.size).toBe(0);
    expect(syncPass).toHaveBeenLastCalledWith(null);
  });

  it("stays signed in through a transient refresh failure", async () => {
    const { manager } = await signedIn({
      "POST /auth/refresh": () => problem(503, "down"),
      "GET /me/mood": () => problem(401, "expired"),
    });
    await expect(manager.api.request("/me/mood")).rejects.toMatchObject({ status: 401 });
    expect(manager.getState().status).toBe("authenticated");
  });
});

describe("SessionManager.logout", () => {
  it("revokes the session server-side, clears everything, and tells other tabs", async () => {
    const { manager, store, syncPass, channels, calls } = setup({
      "POST /auth/login": () => json(tokens()),
      "GET /me": () => json(me()),
      "POST /auth/logout": () => new Response(null, { status: 204 }),
    });
    await manager.login({ email: "a@test.example", password: "pw" });
    await manager.logout();

    expect(
      calls.some(
        (c) => c.path === "/auth/logout" && c.headers.get("Authorization") === "Bearer access-1",
      ),
    ).toBe(true);
    expect(manager.getState().status).toBe("unauthenticated");
    expect(manager.getAccessToken()).toBeNull();
    expect(store.size).toBe(0);
    expect(syncPass).toHaveBeenLastCalledWith(null);
    expect(channels[0]?.postMessage).toHaveBeenCalledWith({ type: "signed-out" });
  });

  it("still signs this browser out when the server call fails", async () => {
    const { manager, store } = setup({
      "POST /auth/login": () => json(tokens()),
      "GET /me": () => json(me()),
      "POST /auth/logout": () => problem(500, "boom"),
    });
    await manager.login({ email: "a@test.example", password: "pw" });
    await manager.logout();
    expect(manager.getState().status).toBe("unauthenticated");
    expect(store.size).toBe(0);
  });

  it("signs out when another tab signs out", async () => {
    const { manager, channels } = setup({
      "POST /auth/login": () => json(tokens()),
      "GET /me": () => json(me()),
    });
    await manager.login({ email: "a@test.example", password: "pw" });
    channels[0]?.onmessage?.({ data: { type: "signed-out" } } as MessageEvent);
    expect(manager.getState().status).toBe("unauthenticated");
    expect(manager.getAccessToken()).toBeNull();
  });
});

describe("SessionManager subscriptions", () => {
  it("notifies subscribers on every state change", async () => {
    const { manager } = setup({
      "POST /auth/login": () => json(tokens()),
      "GET /me": () => json(me()),
    });
    const listener = vi.fn();
    const unsubscribe = manager.subscribe(listener);
    await manager.login({ email: "a@test.example", password: "pw" });
    expect(listener).toHaveBeenCalled();
    unsubscribe();
    listener.mockClear();
    await manager.logout();
    expect(listener).not.toHaveBeenCalled();
  });
});
