import { describe, expect, it } from "vitest";

import { signPass, verifyPass } from "@/lib/auth/pass";

const SECRET = "a".repeat(40);
const NOW = new Date("2026-01-01T00:00:00Z");

describe("portal pass", () => {
  it("round-trips a role", async () => {
    const pass = await signPass("therapist", SECRET, NOW);
    expect(await verifyPass(pass, SECRET, NOW)).toBe("therapist");
  });

  it("rejects a pass signed with another secret", async () => {
    const pass = await signPass("administrator", SECRET, NOW);
    expect(await verifyPass(pass, "b".repeat(40), NOW)).toBeNull();
  });

  it("rejects a tampered role (nobody can edit themselves into an admin)", async () => {
    const pass = await signPass("student", SECRET, NOW);
    const [, signature] = pass.split(".") as [string, string];
    const forged = btoa(JSON.stringify({ r: "administrator", exp: 9999999999 }))
      .replace(/=+$/, "")
      .replace(/\+/g, "-")
      .replace(/\//g, "_");
    expect(await verifyPass(`${forged}.${signature}`, SECRET, NOW)).toBeNull();
  });

  it("rejects an expired pass", async () => {
    const pass = await signPass("student", SECRET, NOW, 60);
    expect(await verifyPass(pass, SECRET, new Date(NOW.getTime() + 61_000))).toBeNull();
    expect(await verifyPass(pass, SECRET, new Date(NOW.getTime() + 30_000))).toBe("student");
  });

  it.each([undefined, "", "abc", "a.b.c", "!!!.???", "."])("never throws on %j", async (value) => {
    expect(await verifyPass(value, SECRET, NOW)).toBeNull();
  });
});
