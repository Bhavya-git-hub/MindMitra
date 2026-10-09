/**
 * Errors from the MindMitra API. The API answers with RFC 9457 `application/problem+json`;
 * `ApiError` carries the parts the UI may show and never the submitted input.
 */

export interface FieldIssue {
  /** Path of the offending field, e.g. ["body", "email"]. */
  loc: string[];
  msg: string;
}

export interface ApiErrorInit {
  status: number;
  title?: string;
  detail?: string;
  requestId?: string | null;
  issues?: FieldIssue[];
  retryAfterSeconds?: number | null;
}

export class ApiError extends Error {
  /** HTTP status, or 0 when the server could not be reached at all. */
  readonly status: number;
  readonly title: string;
  readonly detail: string;
  readonly requestId: string | null;
  readonly issues: FieldIssue[];
  readonly retryAfterSeconds: number | null;

  constructor(init: ApiErrorInit) {
    const detail = init.detail ?? "";
    super(detail || init.title || `Request failed (${init.status})`);
    this.name = "ApiError";
    this.status = init.status;
    this.title = init.title ?? "";
    this.detail = detail;
    this.requestId = init.requestId ?? null;
    this.issues = init.issues ?? [];
    this.retryAfterSeconds = init.retryAfterSeconds ?? null;
  }

  get isNetworkError(): boolean {
    return this.status === 0;
  }

  get isUnauthorized(): boolean {
    return this.status === 401;
  }

  get isRateLimited(): boolean {
    return this.status === 429;
  }

  get isServerError(): boolean {
    return this.status >= 500;
  }

  /** Validation messages keyed by the last path segment (the field name). */
  fieldErrors(): Record<string, string> {
    const out: Record<string, string> = {};
    for (const issue of this.issues) {
      const field = issue.loc[issue.loc.length - 1];
      if (field && !(field in out)) out[field] = issue.msg;
    }
    return out;
  }
}

export function isApiError(error: unknown): error is ApiError {
  return error instanceof ApiError;
}

/**
 * Plain-language message for a failed request. Server `detail` text is written for people
 * (and never carries internals), but network and 5xx failures get a friendlier fallback.
 */
export function describeError(
  error: unknown,
  fallback = "Something went wrong. Please try again.",
): string {
  if (!isApiError(error)) return fallback;
  if (error.isNetworkError) {
    return "We couldn't reach MindMitra. Check your connection and try again.";
  }
  if (error.isRateLimited) {
    const wait = error.retryAfterSeconds;
    return wait
      ? `Too many attempts. Please wait about ${wait} seconds and try again.`
      : "Too many attempts. Please wait a moment and try again.";
  }
  if (error.isServerError) return fallback;
  return error.detail || fallback;
}
