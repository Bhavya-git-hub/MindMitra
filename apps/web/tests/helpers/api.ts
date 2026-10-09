import { vi } from "vitest";

import type { Role } from "@/lib/auth/roles";

export const API = "http://api.test";

export function json(body: unknown, status = 200, headers: Record<string, string> = {}): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json", ...headers },
  });
}

export function problem(
  status: number,
  detail: string,
  extra: Record<string, unknown> = {},
  headers: Record<string, string> = {},
): Response {
  return new Response(
    JSON.stringify({ title: "Problem", status, detail, request_id: "req-1", ...extra }),
    { status, headers: { "Content-Type": "application/problem+json", ...headers } },
  );
}

export const tokens = (role: Role = "student", n = 1) => ({
  access_token: `access-${n}`,
  token_type: "bearer",
  expires_in: 600,
  csrf_token: `csrf-${n}`,
  user: { id: "user-1", role, institution_id: "inst-1" },
});

export const me = (role: Role = "student") => ({
  id: "user-1",
  institution_id: "inst-1",
  email: "asha.verma@test.example",
  full_name: "Asha Verma",
  role,
  status: "active",
  permissions: ["profile:read_own"],
});

export interface RecordedCall {
  method: string;
  path: string;
  headers: Headers;
  body: unknown;
  credentials: RequestCredentials | undefined;
}

type Handler = (call: RecordedCall) => Response | Promise<Response>;

/** A fake `fetch` that routes `"METHOD /path"` (without the /api/v1 prefix) to handlers. */
export function fakeApi(handlers: Record<string, Handler>) {
  const calls: RecordedCall[] = [];
  const fetchFn = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input));
    const path = url.pathname.replace(/^\/api\/v1/, "");
    const method = init?.method ?? "GET";
    const call: RecordedCall = {
      method,
      path,
      headers: new Headers(init?.headers),
      body: typeof init?.body === "string" ? JSON.parse(init.body) : undefined,
      credentials: init?.credentials,
    };
    calls.push(call);
    const handler = handlers[`${method} ${path}`];
    if (!handler) throw new Error(`Unhandled request: ${method} ${path}`);
    return handler(call);
  });
  return { fetch: fetchFn as unknown as typeof fetch, calls, mock: fetchFn };
}
