/**
 * Request proxy (Next.js 16's replacement for middleware). It does two things for every page
 * request: an optimistic role-based redirect using the signed portal pass, and a per-request
 * Content-Security-Policy nonce. Both are defence in depth: the API enforces access.
 */
import { NextResponse, type NextRequest } from "next/server";

import { PASS_COOKIE, verifyPass } from "@/lib/auth/pass";
import { decideAccess } from "@/lib/auth/route-access";
import { buildCsp, generateNonce } from "@/lib/csp";
import { apiBaseUrl, sessionSecret } from "@/lib/env";

export async function proxy(request: NextRequest) {
  const { pathname, search } = request.nextUrl;
  const role = await verifyPass(request.cookies.get(PASS_COOKIE)?.value, sessionSecret());

  const decision = decideAccess(pathname, role, search);
  if (decision.type === "redirect") {
    return NextResponse.redirect(new URL(decision.to, request.url));
  }

  const nonce = generateNonce();
  const csp = buildCsp({
    nonce,
    apiOrigin: new URL(apiBaseUrl()).origin,
    isDev: process.env.NODE_ENV === "development",
  });

  const headers = new Headers(request.headers);
  headers.set("x-nonce", nonce);
  headers.set("Content-Security-Policy", csp);

  const response = NextResponse.next({ request: { headers } });
  response.headers.set("Content-Security-Policy", csp);
  return response;
}

export const config = {
  matcher: [
    {
      source: "/((?!api|_next/static|_next/image|favicon.ico|icon.svg).*)",
      missing: [
        { type: "header", key: "next-router-prefetch" },
        { type: "header", key: "purpose", value: "prefetch" },
      ],
    },
  ],
};
