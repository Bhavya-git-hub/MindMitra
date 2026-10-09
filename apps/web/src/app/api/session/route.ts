/**
 * Portal-pass endpoint. After sign-in the browser asks this same-origin route to set a signed,
 * HttpOnly cookie recording the person's role, so `proxy.ts` can redirect before rendering.
 *
 * The role is never taken from the client: the route forwards the Bearer token to the API's
 * `/me` and signs whatever role the API reports. A forged or expired token yields no pass.
 */
import { NextResponse, type NextRequest } from "next/server";
import { z } from "zod";

import { roleSchema } from "@/lib/api/schemas";
import { PASS_COOKIE, PASS_MAX_AGE_SECONDS, signPass } from "@/lib/auth/pass";
import { API_PREFIX } from "@/lib/api/client";
import { apiInternalUrl, sessionSecret } from "@/lib/env";

const NO_STORE = { "Cache-Control": "no-store" };

const meRoleSchema = z.object({ role: roleSchema });

/** Refuse cross-site callers outright (browsers always send Origin on unsafe methods). */
function sameOrigin(request: NextRequest): boolean {
  const origin = request.headers.get("origin");
  return origin === null || origin === request.nextUrl.origin;
}

function cookieOptions(maxAge: number) {
  return {
    httpOnly: true,
    secure: process.env.NODE_ENV === "production",
    sameSite: "lax" as const,
    path: "/",
    maxAge,
  };
}

export async function POST(request: NextRequest) {
  if (!sameOrigin(request)) {
    return NextResponse.json({ error: "forbidden" }, { status: 403, headers: NO_STORE });
  }
  const authorization = request.headers.get("authorization");
  if (!authorization?.startsWith("Bearer ")) {
    return NextResponse.json({ error: "unauthorized" }, { status: 401, headers: NO_STORE });
  }

  let role;
  try {
    const upstream = await fetch(`${apiInternalUrl()}${API_PREFIX}/me`, {
      headers: { Authorization: authorization, Accept: "application/json" },
      cache: "no-store",
    });
    if (!upstream.ok) {
      return NextResponse.json({ error: "unauthorized" }, { status: 401, headers: NO_STORE });
    }
    const parsed = meRoleSchema.safeParse(await upstream.json());
    if (!parsed.success) throw new Error("unexpected /me response");
    role = parsed.data.role;
  } catch {
    return NextResponse.json({ error: "upstream_unavailable" }, { status: 502, headers: NO_STORE });
  }

  const response = NextResponse.json({ role }, { headers: NO_STORE });
  response.cookies.set(
    PASS_COOKIE,
    await signPass(role, sessionSecret()),
    cookieOptions(PASS_MAX_AGE_SECONDS),
  );
  return response;
}

export async function DELETE(request: NextRequest) {
  if (!sameOrigin(request)) {
    return NextResponse.json({ error: "forbidden" }, { status: 403, headers: NO_STORE });
  }
  const response = new NextResponse(null, { status: 204, headers: NO_STORE });
  response.cookies.set(PASS_COOKIE, "", cookieOptions(0));
  return response;
}
