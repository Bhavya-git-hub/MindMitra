import { portalFor, roleForPath, type Role } from "@/lib/auth/roles";

export type AccessDecision = { type: "next" } | { type: "redirect"; to: string };

/** Pages a signed-in person has no reason to see; they are sent to their own portal instead. */
const GUEST_ONLY_PATHS = new Set(["/login", "/register", "/forgot-password"]);

/**
 * Decide what to do with a request, given the role proven by the portal-pass cookie (or null).
 * Pure so it can be tested exhaustively; `src/proxy.ts` applies it.
 */
export function decideAccess(pathname: string, role: Role | null, search = ""): AccessDecision {
  if (pathname === "/") {
    return { type: "redirect", to: role ? portalFor(role) : "/login" };
  }

  const portalRole = roleForPath(pathname);
  if (portalRole) {
    if (!role) {
      const next = encodeURIComponent(`${pathname}${search}`);
      return { type: "redirect", to: `/login?next=${next}` };
    }
    if (role !== portalRole) return { type: "redirect", to: portalFor(role) };
    return { type: "next" };
  }

  if (role && GUEST_ONLY_PATHS.has(pathname)) {
    return { type: "redirect", to: portalFor(role) };
  }
  return { type: "next" };
}

/**
 * Where to go after signing in. `next` is honoured only when it is a same-site path inside the
 * person's own portal, which also rules out open redirects (`//evil.example`, `https://...`).
 */
export function safeNext(next: string | null | undefined, role: Role): string {
  if (
    next &&
    next.startsWith("/") &&
    !next.startsWith("//") &&
    !next.includes("\\") &&
    !/[\u0000-\u001f]/.test(next) &&
    roleForPath(new URL(next, "http://placeholder.invalid").pathname) === role
  ) {
    return next;
  }
  return portalFor(role);
}
