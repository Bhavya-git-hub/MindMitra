import { NextRequest } from "next/server";
import { afterEach, describe, expect, it, vi } from "vitest";

import { DELETE, POST } from "@/app/api/session/route";
import { PASS_COOKIE, verifyPass } from "@/lib/auth/pass";

import { json, me, problem } from "../helpers/api";

function request(method: "POST" | "DELETE", headers: Record<string, string> = {}) {
  return new NextRequest("http://localhost:3000/api/session", { method, headers });
}

afterEach(() => vi.unstubAllGlobals());

describe("POST /api/session", () => {
  it("signs the role the API reports, not anything the client claims", async () => {
    const upstream = vi.fn(async () => json(me("teacher")));
    vi.stubGlobal("fetch", upstream);

    const res = await POST(
      request("POST", { authorization: "Bearer real-token", "x-role": "administrator" }),
    );

    expect(res.status).toBe(200);
    expect(upstream).toHaveBeenCalledWith(
      "http://api.test/api/v1/me",
      expect.objectContaining({
        headers: expect.objectContaining({ Authorization: "Bearer real-token" }),
      }),
    );
    const cookie = res.cookies.get(PASS_COOKIE);
    expect(cookie?.httpOnly).toBe(true);
    expect(cookie?.sameSite).toBe("lax");
    expect(await verifyPass(cookie?.value, process.env.SESSION_SECRET as string)).toBe("teacher");
    expect(res.headers.get("cache-control")).toBe("no-store");
  });

  it("refuses a request without a token", async () => {
    vi.stubGlobal("fetch", vi.fn());
    const res = await POST(request("POST"));
    expect(res.status).toBe(401);
    expect(res.cookies.get(PASS_COOKIE)).toBeUndefined();
  });

  it("refuses a token the API rejects", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => problem(401, "bad token")),
    );
    const res = await POST(request("POST", { authorization: "Bearer forged" }));
    expect(res.status).toBe(401);
    expect(res.cookies.get(PASS_COOKIE)).toBeUndefined();
  });

  it("reports 502 when the API is unreachable", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw new TypeError("down");
      }),
    );
    const res = await POST(request("POST", { authorization: "Bearer t" }));
    expect(res.status).toBe(502);
  });

  it("rejects cross-site callers", async () => {
    vi.stubGlobal("fetch", vi.fn());
    const res = await POST(
      request("POST", { authorization: "Bearer t", origin: "https://evil.example" }),
    );
    expect(res.status).toBe(403);
  });
});

describe("DELETE /api/session", () => {
  it("expires the pass", async () => {
    const res = await DELETE(request("DELETE"));
    expect(res.status).toBe(204);
    const cookie = res.cookies.get(PASS_COOKIE);
    expect(cookie?.value).toBe("");
    expect(cookie?.maxAge).toBe(0);
  });

  it("rejects cross-site callers", async () => {
    const res = await DELETE(request("DELETE", { origin: "https://evil.example" }));
    expect(res.status).toBe(403);
  });
});
