import { describe, expect, it } from "vitest";

import { isRole, PORTAL_PATHS, portalFor, ROLES, roleForPath } from "@/lib/auth/roles";

describe("roles", () => {
  it("maps every role to its own portal", () => {
    expect(PORTAL_PATHS).toEqual({
      student: "/student",
      therapist: "/therapist",
      teacher: "/teacher",
      administrator: "/admin",
    });
    for (const role of ROLES) expect(portalFor(role)).toBe(PORTAL_PATHS[role]);
  });

  it("recognises roles", () => {
    expect(isRole("teacher")).toBe(true);
    expect(isRole("admin")).toBe(false); // the API role is "administrator"
    expect(isRole(undefined)).toBe(false);
    expect(isRole(42)).toBe(false);
  });

  it("finds the portal a path belongs to", () => {
    expect(roleForPath("/student")).toBe("student");
    expect(roleForPath("/student/account")).toBe("student");
    expect(roleForPath("/admin/users")).toBe("administrator");
    expect(roleForPath("/teacher")).toBe("teacher");
    expect(roleForPath("/login")).toBeNull();
    expect(roleForPath("/")).toBeNull();
  });

  it("does not match look-alike prefixes", () => {
    expect(roleForPath("/students")).toBeNull();
    expect(roleForPath("/administrator")).toBeNull();
    expect(roleForPath("/admin-tools")).toBeNull();
    expect(roleForPath("/therapistx/a")).toBeNull();
  });
});
