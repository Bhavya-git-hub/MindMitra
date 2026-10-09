"use client";

import * as React from "react";

import type { LoginInput } from "@/lib/api/auth-api";
import type { Me } from "@/lib/api/schemas";

import {
  getSessionManager,
  type SessionManager,
  type SessionState,
  type SignedOutReason,
} from "./session-manager";

interface AuthContextValue {
  status: SessionState["status"];
  user: Me | null;
  /** Why the session ended; only set when `status` is "unauthenticated". */
  signedOutReason: SignedOutReason | null;
  manager: SessionManager;
  login: (input: LoginInput) => Promise<Me>;
  logout: () => Promise<void>;
  /** After status "unavailable": check the session again. */
  retry: () => Promise<void>;
}

const AuthContext = React.createContext<AuthContextValue | null>(null);

const SERVER_STATE: SessionState = { status: "loading", user: null };

export function AuthProvider({
  children,
  manager,
}: {
  children: React.ReactNode;
  /** Injected in tests; defaults to the browser-wide manager. */
  manager?: SessionManager;
}) {
  const [resolved] = React.useState(() => manager ?? getSessionManager());
  const state = React.useSyncExternalStore(
    resolved.subscribe,
    resolved.getState,
    () => SERVER_STATE,
  );

  React.useEffect(() => {
    void resolved.bootstrap();
  }, [resolved]);

  const value = React.useMemo<AuthContextValue>(
    () => ({
      status: state.status,
      user: state.user,
      signedOutReason: state.status === "unauthenticated" ? state.reason : null,
      manager: resolved,
      login: (input) => resolved.login(input),
      logout: () => resolved.logout(),
      retry: () => resolved.retry(),
    }),
    [state, resolved],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = React.useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside <AuthProvider>");
  return ctx;
}
