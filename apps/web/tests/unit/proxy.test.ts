import { NextRequest } from "next/server";
import { describe, expect, it } from "vitest";

import { PASS_COOKIE, signPass } from "@/lib/auth/pass";
import type { Role } from "@/lib/auth/roles";
import { proxy } from "@/proxy";

async function run(path: string, role?: Role | "forged") {
  const headers = new Headers();
  if (role === "forged") headers.set("cookie", `${PASS_COOKIE}=eyJyIjoiYWRtaW5pc3RyYXRvciJ9.AAAA`);
  else if (role) {
    const pass = await signPass(role, process.env.SESSION_SECRET as string);
    headers.set("cookie", `${PASS_COOKIE}=${pass}`);
  }
  return proxy(new NextRequest(`http://localhost:3000${path}`, { headers }));
}

const location = (res: Response) => res.headers.get("location");

describe("proxy", () => {
  it("sends a signed-out visitor from a portal to login with a next param", async () => {
    const res = await run("/student/account");
    expect(res.status).toBe(307);
    expect(location(res)).toBe("http://localhost:3000/login?next=%2Fstudent%2Faccount");
  });

  it("sends each role away from other portals", async () => {
    expect(location(await run("/admin", "student"))).toBe("http://localhost:3000/student");
    expect(location(await run("/therapist", "teacher"))).toBe("http://localhost:3000/teacher");
    expect(location(await run("/student", "administrator"))).toBe("http://localhost:3000/admin");
  });

  it("lets a role into its own portal", async () => {
    const res = await run("/therapist/account", "therapist");
    expect(res.status).toBe(200);
    expect(res.headers.get("location")).toBeNull();
  });

  it("treats a forged pass as signed out", async () => {
    const res = await run("/admin", "forged");
    expect(location(res)).toContain("/login?next=");
  });

  it("redirects / and the guest pages by role", async () => {
    expect(location(await run("/", "teacher"))).toBe("http://localhost:3000/teacher");
    expect(location(await run("/login", "student"))).toBe("http://localhost:3000/student");
    expect(location(await run("/"))).toBe("http://localhost:3000/login");
  });

  it("sets a nonce-based CSP that matches the nonce passed to the page", async () => {
    const res = await run("/login");
    const csp = res.headers.get("content-security-policy") ?? "";
    const nonce = /'nonce-([^']+)'/.exec(csp)?.[1];
    expect(nonce).toBeTruthy();
    expect(csp).toContain("connect-src 'self' http://api.test");
    // The nonce reaches the page through a request header override.
    expect(res.headers.get("x-middleware-override-headers")).toContain("x-nonce");
    expect(res.headers.get("x-middleware-request-x-nonce")).toBe(nonce);
  });
});
