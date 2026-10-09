import { describe, expect, it, vi } from "vitest";
import { z } from "zod";

import { createApiClient } from "@/lib/api/client";
import { ApiError, describeError } from "@/lib/api/errors";

import { API, fakeApi, json, problem } from "../helpers/api";

const widget = z.object({ id: z.number() });

function client(
  handlers: Parameters<typeof fakeApi>[0],
  hooks: Partial<Parameters<typeof createApiClient>[0]["hooks"]> = {},
) {
  const api = fakeApi(handlers);
  return {
    ...api,
    client: createApiClient({
      fetchImpl: api.fetch,
      baseUrl: () => API,
      hooks: { getAccessToken: () => "tok", onUnauthorized: async () => false, ...hooks },
    }),
  };
}

describe("api client", () => {
  it("sends the Bearer token, JSON body and credentials, and validates the response", async () => {
    const { client: c, calls } = client({ "POST /things": () => json({ id: 7 }) });
    const result = await c.request("/things", { method: "POST", body: { a: 1 }, schema: widget });
    expect(result).toEqual({ id: 7 });
    expect(calls[0]?.headers.get("Authorization")).toBe("Bearer tok");
    expect(calls[0]?.headers.get("Content-Type")).toBe("application/json");
    expect(calls[0]?.body).toEqual({ a: 1 });
    expect(calls[0]?.credentials).toBe("include");
  });

  it("omits the token when auth is off", async () => {
    const { client: c, calls } = client({ "GET /open": () => json({ id: 1 }) });
    await c.request("/open", { schema: widget, auth: false });
    expect(calls[0]?.headers.has("Authorization")).toBe(false);
  });

  it("returns undefined for 204", async () => {
    const { client: c } = client({ "POST /bye": () => new Response(null, { status: 204 }) });
    await expect(c.request("/bye", { method: "POST" })).resolves.toBeUndefined();
  });

  it("turns problem+json into an ApiError with field errors and request id", async () => {
    const { client: c } = client({
      "POST /x": () =>
        problem(422, "The request is not valid.", {
          errors: [
            { loc: ["body", "email"], msg: "value is not a valid email" },
            { loc: ["body", "age"], msg: "too low" },
          ],
        }),
    });
    const error = await c.request("/x", { method: "POST", body: {} }).catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    const api = error as ApiError;
    expect(api.status).toBe(422);
    expect(api.requestId).toBe("req-1");
    expect(api.fieldErrors()).toEqual({ email: "value is not a valid email", age: "too low" });
  });

  it("reads Retry-After from rate-limit responses", async () => {
    const { client: c } = client({
      "GET /x": () => problem(429, "Slow down", {}, { "Retry-After": "17" }),
    });
    const error = (await c.request("/x").catch((e: unknown) => e)) as ApiError;
    expect(error.isRateLimited).toBe(true);
    expect(error.retryAfterSeconds).toBe(17);
    expect(describeError(error)).toContain("17 seconds");
  });

  it("copes with non-JSON error bodies", async () => {
    const { client: c } = client({
      "GET /x": () => new Response("<html>bad gateway</html>", { status: 502 }),
    });
    const error = (await c.request("/x").catch((e: unknown) => e)) as ApiError;
    expect(error.status).toBe(502);
    expect(describeError(error)).toBe("Something went wrong. Please try again.");
  });

  it("reports an unreachable server as status 0", async () => {
    const failing = vi.fn(async () => {
      throw new TypeError("Failed to fetch");
    });
    const c = createApiClient({
      fetchImpl: failing as unknown as typeof fetch,
      baseUrl: () => API,
      hooks: { getAccessToken: () => null, onUnauthorized: async () => false },
    });
    const error = (await c.request("/x").catch((e: unknown) => e)) as ApiError;
    expect(error.isNetworkError).toBe(true);
    expect(describeError(error)).toContain("couldn't reach");
  });

  it("rejects a response that does not match the schema", async () => {
    const { client: c } = client({ "GET /x": () => json({ id: "nope" }) });
    const error = (await c.request("/x", { schema: widget }).catch((e: unknown) => e)) as ApiError;
    expect(error).toBeInstanceOf(ApiError);
    expect(error.title).toBe("Unexpected response");
  });

  describe("401 handling", () => {
    it("retries once with the new token after a successful recovery", async () => {
      let token = "old";
      let hits = 0;
      const { client: c, calls } = client(
        {
          "GET /secret": ({ headers }) => {
            hits += 1;
            return headers.get("Authorization") === "Bearer new"
              ? json({ id: 1 })
              : problem(401, "Expired");
          },
        },
        {
          getAccessToken: () => token,
          onUnauthorized: async (rejected) => {
            expect(rejected).toBe("old");
            token = "new";
            return true;
          },
        },
      );
      await expect(c.request("/secret", { schema: widget })).resolves.toEqual({ id: 1 });
      expect(hits).toBe(2);
      expect(calls[1]?.headers.get("Authorization")).toBe("Bearer new");
    });

    it("does not loop: a second 401 is returned as an error", async () => {
      let recoveries = 0;
      const { client: c, mock } = client(
        { "GET /secret": () => problem(401, "Nope") },
        {
          onUnauthorized: async () => {
            recoveries += 1;
            return true;
          },
        },
      );
      const error = (await c.request("/secret").catch((e: unknown) => e)) as ApiError;
      expect(error.isUnauthorized).toBe(true);
      expect(recoveries).toBe(1);
      expect(mock).toHaveBeenCalledTimes(2);
    });

    it("returns the 401 when recovery fails", async () => {
      const { client: c, mock } = client({ "GET /secret": () => problem(401, "Nope") });
      await expect(c.request("/secret")).rejects.toMatchObject({ status: 401 });
      expect(mock).toHaveBeenCalledTimes(1);
    });

    it("never tries to recover for unauthenticated calls (login)", async () => {
      const onUnauthorized = vi.fn(async () => true);
      const { client: c } = client(
        { "POST /auth/login": () => problem(401, "Invalid credentials") },
        { onUnauthorized },
      );
      await expect(c.request("/auth/login", { method: "POST", auth: false })).rejects.toMatchObject(
        { status: 401 },
      );
      expect(onUnauthorized).not.toHaveBeenCalled();
    });
  });
});
