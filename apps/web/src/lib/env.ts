/**
 * Validated environment access (CLAUDE.md rules 8 and 9: secrets come from the environment,
 * nothing is hard-coded). Everything is read lazily so `next build` works without secrets and
 * a missing value fails loudly at the point of use.
 */
import { z } from "zod";

const urlSchema = z.url({ protocol: /^https?$/ });
const secretSchema = z.string().min(32, "must be at least 32 characters");

/** Browser-visible base URL of the MindMitra API, e.g. https://api.example.org. */
export function apiBaseUrl(): string {
  // Next.js inlines `process.env.NEXT_PUBLIC_*` only for static property access.
  const parsed = urlSchema.safeParse(process.env.NEXT_PUBLIC_API_BASE_URL);
  if (!parsed.success) {
    throw new Error("NEXT_PUBLIC_API_BASE_URL must be set to the API's http(s) URL");
  }
  return parsed.data.replace(/\/+$/, "");
}

/** Where the web server reaches the API. Defaults to the public URL. Server-side only. */
export function apiInternalUrl(): string {
  const raw = process.env.API_INTERNAL_URL;
  if (!raw) return apiBaseUrl();
  const parsed = urlSchema.safeParse(raw);
  if (!parsed.success) throw new Error("API_INTERNAL_URL must be an http(s) URL");
  return parsed.data.replace(/\/+$/, "");
}

/** Key that signs the portal-pass cookie. Server-side only. */
export function sessionSecret(): string {
  const parsed = secretSchema.safeParse(process.env.SESSION_SECRET);
  if (!parsed.success) {
    throw new Error(`SESSION_SECRET ${parsed.error.issues[0]?.message ?? "is required"}`);
  }
  return parsed.data;
}

/** The design-system showcase is development-only unless explicitly enabled. */
export function designSystemEnabled(): boolean {
  return process.env.NODE_ENV !== "production" || process.env.ENABLE_DESIGN_SYSTEM === "true";
}
