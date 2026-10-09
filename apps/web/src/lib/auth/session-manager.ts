/**
 * Browser session manager (ADR 0003, ADR 0004).
 *
 * - The short-lived access token lives in memory only.
 * - The CSRF token that authorises `/auth/refresh` is kept in localStorage so a page reload can
 *   obtain a new access token. It cannot be used without the HttpOnly refresh cookie, which
 *   JavaScript never sees; this tradeoff is documented in ADR 0004.
 * - Refreshes are single-use on the server, so they are serialised: in-flight calls are shared
 *   inside a tab and a Web Lock serialises them across tabs.
 * - Signing out in one tab signs out every tab (BroadcastChannel).
 * - After sign-in the same-origin `/api/session` route sets a signed, HttpOnly "portal pass"
 *   cookie so the proxy can redirect by role before the page renders. The pass is a UX hint;
 *   the API enforces access.
 */
import { createAuthApi, type AuthApi, type LoginInput } from "@/lib/api/auth-api";
import { createApiClient, type ApiClient } from "@/lib/api/client";
import { isApiError } from "@/lib/api/errors";
import type { Me, TokenOut } from "@/lib/api/schemas";

export const CSRF_STORAGE_KEY = "mm.csrf";
const REFRESH_LOCK = "mm-refresh";
const CHANNEL_NAME = "mm-auth";

/**
 * Why there is no session: the person chose to sign out (`"user"`), or there simply is none
 * (never signed in, expired, revoked). The route guard only remembers where someone was
 * heading in the second case.
 */
export type SignedOutReason = "user" | "expired";

export type SessionState =
  | { status: "loading"; user: null }
  | { status: "authenticated"; user: Me }
  | { status: "unauthenticated"; user: null; reason: SignedOutReason }
  /** The session could not be checked (offline, API down). Nobody is signed out; retry. */
  | { status: "unavailable"; user: null };

export interface SessionManagerDeps {
  /** Overrides for tests; the defaults use the real browser APIs. */
  fetchImpl?: typeof fetch;
  baseUrl?: () => string;
  storage?: Pick<Storage, "getItem" | "setItem" | "removeItem"> | null;
  locks?: Pick<LockManager, "request"> | null;
  createChannel?: (() => Pick<BroadcastChannel, "postMessage" | "close" | "onmessage">) | null;
  /** Asks the same-origin route handler to set (token) or clear (null) the portal pass. */
  syncPass?: (accessToken: string | null) => Promise<void>;
}

const LOADING: SessionState = { status: "loading", user: null };
const UNAVAILABLE: SessionState = { status: "unavailable", user: null };
const EXPIRED: SessionState = { status: "unauthenticated", user: null, reason: "expired" };
const SIGNED_OUT_BY_USER: SessionState = { status: "unauthenticated", user: null, reason: "user" };

async function defaultSyncPass(accessToken: string | null): Promise<void> {
  try {
    await fetch("/api/session", {
      method: accessToken ? "POST" : "DELETE",
      headers: accessToken ? { Authorization: `Bearer ${accessToken}` } : undefined,
      credentials: "same-origin",
      cache: "no-store",
    });
  } catch {
    // The pass only improves redirects; a failure must never break sign-in or sign-out.
  }
}

export class SessionManager {
  readonly api: ApiClient;
  readonly auth: AuthApi;

  private accessToken: string | null = null;
  private state: SessionState = LOADING;
  private readonly listeners = new Set<() => void>();
  private refreshInFlight: Promise<boolean> | null = null;
  private bootstrapInFlight: Promise<void> | null = null;
  private channel: Pick<BroadcastChannel, "postMessage" | "close" | "onmessage"> | null = null;

  private readonly storage: SessionManagerDeps["storage"];
  private readonly locks: SessionManagerDeps["locks"];
  private readonly syncPass: NonNullable<SessionManagerDeps["syncPass"]>;

  constructor(deps: SessionManagerDeps = {}) {
    this.storage =
      deps.storage !== undefined
        ? deps.storage
        : typeof window !== "undefined"
          ? safeLocalStorage()
          : null;
    this.locks =
      deps.locks !== undefined
        ? deps.locks
        : typeof navigator !== "undefined" && "locks" in navigator
          ? navigator.locks
          : null;
    this.syncPass = deps.syncPass ?? defaultSyncPass;

    this.api = createApiClient({
      fetchImpl: deps.fetchImpl,
      baseUrl: deps.baseUrl,
      hooks: {
        getAccessToken: () => this.accessToken,
        onUnauthorized: (rejected) => this.recoverFrom401(rejected),
      },
    });
    this.auth = createAuthApi(this.api);

    const makeChannel =
      deps.createChannel !== undefined
        ? deps.createChannel
        : typeof BroadcastChannel !== "undefined"
          ? () => new BroadcastChannel(CHANNEL_NAME)
          : null;
    if (makeChannel) {
      this.channel = makeChannel();
      this.channel.onmessage = (event: MessageEvent) => {
        if ((event.data as { type?: string } | null)?.type === "signed-out") {
          this.clearLocal();
          this.setState(SIGNED_OUT_BY_USER);
        }
      };
    }
  }

  // ---- store interface (useSyncExternalStore) -------------------------------------------------

  subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  };

  getState = (): SessionState => this.state;

  getAccessToken(): string | null {
    return this.accessToken;
  }

  private setState(next: SessionState): void {
    this.state = next;
    for (const listener of this.listeners) listener();
  }

  // ---- lifecycle ------------------------------------------------------------------------------

  /** Restores a session after a reload. Safe to call repeatedly (and twice by StrictMode). */
  bootstrap(): Promise<void> {
    if (this.state.status !== "loading") return Promise.resolve();
    this.bootstrapInFlight ??= this.restore().finally(() => {
      this.bootstrapInFlight = null;
    });
    return this.bootstrapInFlight;
  }

  private async restore(): Promise<void> {
    if (!this.readCsrf()) {
      this.clearLocal();
      await this.syncPass(null); // a stale pass must not bounce /login back to a portal
      this.setState(EXPIRED);
      return;
    }
    const refreshed = await this.refresh();
    if (!refreshed) {
      // refresh() already ended the session if the server rejected it. If the server was
      // merely unreachable, say so rather than pretend the person is signed out: redirecting
      // to /login would bounce straight back (the portal pass is still valid) and loop.
      if (this.state.status === "loading") this.setState(UNAVAILABLE);
      return;
    }
    try {
      const me = await this.auth.me();
      await this.syncPass(this.accessToken);
      this.setState({ status: "authenticated", user: me });
    } catch (error) {
      if (isApiError(error) && (error.status === 401 || error.status === 403)) {
        await this.endSession();
      } else {
        this.setState(UNAVAILABLE);
      }
    }
  }

  /** Tries again after "unavailable". */
  retry(): Promise<void> {
    if (this.state.status !== "unavailable") return Promise.resolve();
    this.setState(LOADING);
    return this.bootstrap();
  }

  async login(input: LoginInput): Promise<Me> {
    const tokens = await this.auth.login(input);
    this.applyTokens(tokens);
    try {
      const me = await this.auth.me();
      await this.syncPass(tokens.access_token);
      this.setState({ status: "authenticated", user: me });
      return me;
    } catch (error) {
      await this.endSession();
      throw error;
    }
  }

  async logout(): Promise<void> {
    try {
      await this.auth.logout();
    } catch {
      // Whatever the server said, this browser is done with the session.
    }
    await this.endSession({ byUser: true });
  }

  // ---- refresh --------------------------------------------------------------------------------

  /** Exchanges the refresh cookie for a new access token. Resolves false when that fails. */
  refresh(): Promise<boolean> {
    this.refreshInFlight ??= this.withRefreshLock(() => this.doRefresh()).finally(() => {
      this.refreshInFlight = null;
    });
    return this.refreshInFlight;
  }

  private async doRefresh(): Promise<boolean> {
    // Read inside the lock: another tab may have rotated the CSRF token while we waited.
    const csrf = this.readCsrf();
    if (!csrf) return false;
    try {
      this.applyTokens(await this.auth.refresh(csrf));
      return true;
    } catch (error) {
      // 4xx (except 429) means the session is over; network errors, 429 and 5xx are transient.
      if (isApiError(error) && error.status >= 400 && error.status < 500 && error.status !== 429) {
        await this.endSession();
      }
      return false;
    }
  }

  private async withRefreshLock<T>(task: () => Promise<T>): Promise<T> {
    if (!this.locks) return task();
    return this.locks.request(REFRESH_LOCK, task) as Promise<T>;
  }

  private async recoverFrom401(rejectedToken: string | null): Promise<boolean> {
    // Someone already replaced the token the request used: just retry with the new one.
    if (this.accessToken && this.accessToken !== rejectedToken) return true;
    // A server rejection already ended the session inside refresh(); a transient failure
    // (offline, 5xx) keeps it so the user is not signed out by a bad connection.
    return this.refresh();
  }

  // ---- internals ------------------------------------------------------------------------------

  private applyTokens(tokens: TokenOut): void {
    this.accessToken = tokens.access_token;
    this.writeCsrf(tokens.csrf_token);
  }

  private clearLocal(): void {
    this.accessToken = null;
    this.removeCsrf();
  }

  private async endSession({ byUser = false } = {}): Promise<void> {
    this.clearLocal();
    this.setState(byUser ? SIGNED_OUT_BY_USER : EXPIRED);
    await this.syncPass(null);
    if (byUser) this.channel?.postMessage({ type: "signed-out" });
  }

  private readCsrf(): string | null {
    try {
      return this.storage?.getItem(CSRF_STORAGE_KEY) ?? null;
    } catch {
      return null;
    }
  }

  private writeCsrf(value: string): void {
    try {
      this.storage?.setItem(CSRF_STORAGE_KEY, value);
    } catch {
      // Storage may be blocked (private mode); the session then lasts until the next reload.
    }
  }

  private removeCsrf(): void {
    try {
      this.storage?.removeItem(CSRF_STORAGE_KEY);
    } catch {
      // ignore
    }
  }

  dispose(): void {
    this.channel?.close();
    this.listeners.clear();
  }
}

function safeLocalStorage(): Storage | null {
  try {
    return window.localStorage;
  } catch {
    return null;
  }
}

let instance: SessionManager | null = null;

/** The browser-wide session manager. */
export function getSessionManager(): SessionManager {
  instance ??= new SessionManager();
  return instance;
}

/** Test helper: drop the singleton so each test starts clean. */
export function resetSessionManagerForTests(): void {
  instance?.dispose();
  instance = null;
}
