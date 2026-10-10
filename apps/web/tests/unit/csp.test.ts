import { describe, expect, it } from "vitest";

import { buildCsp, generateNonce } from "@/lib/csp";

describe("content security policy", () => {
  const prod = buildCsp({ nonce: "N0NCE", apiOrigin: "https://api.example.org", isDev: false });
  const dev = buildCsp({ nonce: "N0NCE", apiOrigin: "http://localhost:8000", isDev: true });

  it("only allows scripts that carry the nonce", () => {
    expect(prod).toContain("script-src 'self' 'nonce-N0NCE' 'strict-dynamic'");
    expect(prod).not.toContain("unsafe-eval");
    expect(prod).not.toMatch(/script-src[^;]*unsafe-inline/);
  });

  it("allows connections only to itself and the API, including its WebSocket", () => {
    expect(prod).toContain("connect-src 'self' https://api.example.org wss://api.example.org;");
    expect(dev).toContain("connect-src 'self' http://localhost:8000 ws://localhost:8000");
  });

  it("forbids framing, plugins and foreign form posts", () => {
    for (const d of [
      "frame-ancestors 'none'",
      "object-src 'none'",
      "form-action 'self'",
      "base-uri 'self'",
    ]) {
      expect(prod).toContain(d);
    }
  });

  it("upgrades insecure requests in production only", () => {
    expect(prod).toContain("upgrade-insecure-requests");
    expect(dev).not.toContain("upgrade-insecure-requests");
    expect(dev).toContain("'unsafe-eval'");
  });

  it("generates a fresh nonce each time", () => {
    expect(generateNonce()).not.toBe(generateNonce());
    expect(generateNonce()).toMatch(/^[A-Za-z0-9+/=]{20,}$/);
  });
});
