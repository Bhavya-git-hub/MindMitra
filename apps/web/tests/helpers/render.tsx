import { render, type RenderResult } from "@testing-library/react";
import * as React from "react";
import { vi } from "vitest";

import { ModalProvider } from "@/components/providers/modal-provider";
import { Toaster } from "@/components/ui/sonner";
import { TooltipProvider } from "@/components/ui/tooltip";
import { AuthProvider } from "@/lib/auth/auth-context";
import type { Role } from "@/lib/auth/roles";
import { SessionManager, CSRF_STORAGE_KEY } from "@/lib/auth/session-manager";

import { API, fakeApi, json, me, problem, tokens } from "./api";

type Handlers = Parameters<typeof fakeApi>[0];

export interface TestSession {
  manager: SessionManager;
  api: ReturnType<typeof fakeApi>;
  syncPass: ReturnType<typeof vi.fn>;
}

/** A session manager wired to a fake API. `signedInAs` starts it from a restorable session. */
export function makeSession(
  handlers: Handlers = {},
  { signedInAs }: { signedInAs?: Role } = {},
): TestSession {
  const defaults: Handlers = signedInAs
    ? {
        "POST /auth/refresh": () => json(tokens(signedInAs, 2)),
        "GET /me": () => json(me(signedInAs)),
        "POST /auth/logout": () => new Response(null, { status: 204 }),
      }
    : {};
  const api = fakeApi({ ...defaults, ...handlers });
  const store = new Map<string, string>(signedInAs ? [[CSRF_STORAGE_KEY, "csrf-1"]] : []);
  const syncPass = vi.fn(async () => {});
  const manager = new SessionManager({
    fetchImpl: api.fetch,
    baseUrl: () => API,
    storage: {
      getItem: (k) => store.get(k) ?? null,
      setItem: (k, v) => void store.set(k, v),
      removeItem: (k) => void store.delete(k),
    },
    locks: null,
    createChannel: null,
    syncPass,
  });
  return { manager, api, syncPass };
}

export function renderWithApp(
  ui: React.ReactElement,
  session: TestSession = makeSession(),
): RenderResult & { session: TestSession } {
  const result = render(
    <TooltipProvider>
      <ModalProvider>
        <AuthProvider manager={session.manager}>
          {ui}
          <Toaster />
        </AuthProvider>
      </ModalProvider>
    </TooltipProvider>,
  );
  return Object.assign(result, { session });
}

export { json, me, problem, tokens };
