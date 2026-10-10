/**
 * The single typed HTTP client for the MindMitra API (CLAUDE.md: no ad-hoc fetch calls in
 * components). It prefixes `/api/v1`, attaches the in-memory Bearer token, parses RFC 9457
 * problem responses into `ApiError`, validates success bodies with zod, and retries an
 * authenticated request once after the session has been refreshed.
 */
import type { z } from "zod";

import { apiBaseUrl } from "@/lib/env";

import { ApiError, type FieldIssue } from "./errors";
import { problemSchema } from "./schemas";

export const API_PREFIX = "/api/v1";

export interface ApiClientHooks {
  getAccessToken: () => string | null;
  /**
   * Called after a 401 on an authenticated request, with the token that was rejected.
   * Resolve `true` when a different, fresh access token is now available, so the request is
   * retried once.
   */
  onUnauthorized: (rejectedToken: string | null) => Promise<boolean>;
}

export interface RequestOptions<T> {
  method?: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  body?: unknown;
  /** Validates the response body. Omit for responses without a body (204). */
  schema?: z.ZodType<T>;
  /** `text` returns the body as a string (a CSV download) and skips schema validation. */
  responseType?: "json" | "text";
  /** Attach the Bearer token and refresh-and-retry on 401. Defaults to true. */
  auth?: boolean;
  headers?: Record<string, string>;
  signal?: AbortSignal;
}

export interface ApiClient {
  request<T = void>(path: string, options?: RequestOptions<T>): Promise<T>;
}

interface ClientConfig {
  hooks: ApiClientHooks;
  baseUrl?: () => string;
  fetchImpl?: typeof fetch;
}

async function parseProblem(response: Response): Promise<ApiError> {
  let title: string | undefined;
  let detail: string | undefined;
  let requestId: string | null = null;
  let issues: FieldIssue[] = [];
  try {
    const parsed = problemSchema.safeParse(await response.json());
    if (parsed.success) {
      title = parsed.data.title;
      detail = parsed.data.detail;
      requestId = parsed.data.request_id ?? null;
      issues = (parsed.data.errors ?? []).map((e) => ({
        loc: e.loc.map(String),
        msg: e.msg,
      }));
    }
  } catch {
    // Not JSON (a proxy error page, for example): fall back to the status alone.
  }
  const retryAfter = Number(response.headers.get("Retry-After"));
  return new ApiError({
    status: response.status,
    title,
    detail,
    requestId,
    issues,
    retryAfterSeconds: Number.isFinite(retryAfter) && retryAfter > 0 ? retryAfter : null,
  });
}

export function createApiClient({
  hooks,
  baseUrl = apiBaseUrl,
  fetchImpl,
}: ClientConfig): ApiClient {
  async function send(path: string, options: RequestOptions<unknown>, token: string | null) {
    const headers: Record<string, string> = {
      Accept: options.responseType === "text" ? "text/csv" : "application/json",
      ...options.headers,
    };
    if (options.body !== undefined) headers["Content-Type"] = "application/json";
    if (token) headers.Authorization = `Bearer ${token}`;

    const doFetch = fetchImpl ?? fetch;
    try {
      return await doFetch(`${baseUrl()}${API_PREFIX}${path}`, {
        method: options.method ?? "GET",
        headers,
        body: options.body === undefined ? undefined : JSON.stringify(options.body),
        // The refresh cookie is scoped to /api/v1/auth, so sending credentials is harmless
        // elsewhere and required for login, refresh and logout.
        credentials: "include",
        cache: "no-store",
        signal: options.signal,
      });
    } catch (cause) {
      if (cause instanceof DOMException && cause.name === "AbortError") throw cause;
      throw new ApiError({ status: 0, title: "Network error", detail: "" });
    }
  }

  async function request<T>(path: string, options: RequestOptions<T> = {}): Promise<T> {
    const useAuth = options.auth ?? true;
    const token = useAuth ? hooks.getAccessToken() : null;
    let response = await send(path, options, token);

    if (response.status === 401 && useAuth && (await hooks.onUnauthorized(token))) {
      response = await send(path, options, hooks.getAccessToken());
    }

    if (!response.ok) throw await parseProblem(response);
    if (options.responseType === "text") return (await response.text()) as T;
    if (response.status === 204 || !options.schema) return undefined as T;

    const body: unknown = await response.json();
    const parsed = options.schema.safeParse(body);
    if (!parsed.success) {
      throw new ApiError({
        status: response.status,
        title: "Unexpected response",
        detail: "The server sent a response we could not understand.",
      });
    }
    return parsed.data;
  }

  return { request };
}
