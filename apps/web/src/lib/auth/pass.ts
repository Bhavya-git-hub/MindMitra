/**
 * The portal pass: a small signed, HttpOnly cookie that records which portal this browser
 * last signed in to. `src/proxy.ts` reads it to redirect before rendering.
 *
 * It is an optimistic UX hint, not an authority. It carries no tokens or personal data, it can
 * outlive the real session (the page then signs the person out and clears it), and the API
 * still authorizes every call. It is signed so nobody can edit their own role into it.
 */
import { isRole, type Role } from "@/lib/auth/roles";

export const PASS_COOKIE = process.env.NODE_ENV === "production" ? "__Host-mm_portal" : "mm_portal";
/** Matches the longest session the API grants (students, 30 days). */
export const PASS_MAX_AGE_SECONDS = 30 * 24 * 60 * 60;

const encoder = new TextEncoder();

function toBase64Url(bytes: Uint8Array): string {
  let binary = "";
  for (const b of bytes) binary += String.fromCharCode(b);
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

function fromBase64Url(value: string): Uint8Array<ArrayBuffer> | null {
  if (!/^[A-Za-z0-9_-]*$/.test(value)) return null;
  try {
    const binary = atob(value.replace(/-/g, "+").replace(/_/g, "/"));
    const bytes = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
    return bytes;
  } catch {
    return null;
  }
}

function hmacKey(secret: string, usage: KeyUsage) {
  return crypto.subtle.importKey(
    "raw",
    encoder.encode(secret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    [usage],
  );
}

export async function signPass(
  role: Role,
  secret: string,
  now: Date = new Date(),
  ttlSeconds: number = PASS_MAX_AGE_SECONDS,
): Promise<string> {
  const payload = toBase64Url(
    encoder.encode(JSON.stringify({ r: role, exp: Math.floor(now.getTime() / 1000) + ttlSeconds })),
  );
  const signature = await crypto.subtle.sign(
    "HMAC",
    await hmacKey(secret, "sign"),
    encoder.encode(payload),
  );
  return `${payload}.${toBase64Url(new Uint8Array(signature))}`;
}

/** The role in a valid, unexpired pass; null for anything else (never throws). */
export async function verifyPass(
  token: string | undefined,
  secret: string,
  now: Date = new Date(),
): Promise<Role | null> {
  if (!token) return null;
  const parts = token.split(".");
  if (parts.length !== 2) return null;
  const [payload, signature] = parts as [string, string];
  const sigBytes = fromBase64Url(signature);
  if (!sigBytes) return null;
  // `subtle.verify` compares in constant time.
  const valid = await crypto.subtle.verify(
    "HMAC",
    await hmacKey(secret, "verify"),
    sigBytes,
    encoder.encode(payload),
  );
  if (!valid) return null;
  const bytes = fromBase64Url(payload);
  if (!bytes) return null;
  try {
    const claims: unknown = JSON.parse(new TextDecoder().decode(bytes));
    if (typeof claims !== "object" || claims === null) return null;
    const { r, exp } = claims as { r?: unknown; exp?: unknown };
    if (!isRole(r) || typeof exp !== "number" || exp * 1000 <= now.getTime()) return null;
    return r;
  } catch {
    return null;
  }
}
