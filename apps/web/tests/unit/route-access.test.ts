import { describe, expect, it } from "vitest";

import { decideAccess, safeNext } from "@/lib/auth/route-access";
import { ROLES, type Role } from "@/lib/auth/roles";

const redirect = (to: string) => ({ type: "redirect", to });
const next = { type: "next" };

describe("decideAccess", () => {
  it("sends signed-out visitors from every portal to /login, remembering the page", () => {
    expect(decideAccess("/student", null)).toEqual(redirect("/login?next=%2Fstudent"));
    expect(decideAccess("/admin/users", null, "?tab=1")).toEqual(
      redirect("/login?next=%2Fadmin%2Fusers%3Ftab%3D1"),
    );
  });

  it("lets each role into its own portal and nowhere else", () => {
    for (const role of ROLES) {
      for (const other of ROLES) {
        const path = `/${other === "administrator" ? "admin" : other}/account`;
        const decision = decideAccess(path, role);
        if (role === other) expect(decision).toEqual(next);
        else expect(decision.type).toBe("redirect");
      }
    }
  });

  it.each<[Role, string]>([
    ["student", "/student"],
    ["therapist", "/therapist"],
    ["teacher", "/teacher"],
    ["administrator", "/admin"],
  ])("sends a %s who opens another portal home to %s", (role, home) => {
    const foreign = ROLES.filter((r) => r !== role)[0] as Role;
    const path = foreign === "administrator" ? "/admin" : `/${foreign}`;
    expect(decideAccess(path, role)).toEqual(redirect(home));
  });

  it("redirects / by role", () => {
    expect(decideAccess("/", null)).toEqual(redirect("/login"));
    expect(decideAccess("/", "teacher")).toEqual(redirect("/teacher"));
  });

  it("keeps signed-in people off the guest pages", () => {
    for (const path of ["/login", "/register", "/forgot-password"]) {
      expect(decideAccess(path, "student")).toEqual(redirect("/student"));
      expect(decideAccess(path, null)).toEqual(next);
    }
  });

  it("leaves public pages alone for everyone", () => {
    for (const path of ["/help", "/verify-email", "/reset-password", "/design-system"]) {
      expect(decideAccess(path, null)).toEqual(next);
      expect(decideAccess(path, "administrator")).toEqual(next);
    }
  });
});

describe("safeNext", () => {
  it("honours a path inside the person's own portal", () => {
    expect(safeNext("/student/account", "student")).toBe("/student/account");
    expect(safeNext("/admin/users?x=1", "administrator")).toBe("/admin/users?x=1");
  });

  it("falls back to the portal home for another role's pages", () => {
    expect(safeNext("/therapist/notes", "student")).toBe("/student");
    expect(safeNext("/login", "student")).toBe("/student");
  });

  it.each([
    "//evil.example",
    "//evil.example/student",
    "https://evil.example/student",
    "javascript:alert(1)",
    "/\\evil.example",
    "/student\\..\\x",
    "/student\n/evil",
    "student",
    "",
  ])("rejects unsafe value %j", (value) => {
    expect(safeNext(value, "student")).toBe("/student");
  });

  it("handles missing values", () => {
    expect(safeNext(undefined, "teacher")).toBe("/teacher");
    expect(safeNext(null, "therapist")).toBe("/therapist");
  });

  it("does not let path tricks cross into another portal", () => {
    expect(safeNext("/student/../admin", "student")).toBe("/student");
  });
});
