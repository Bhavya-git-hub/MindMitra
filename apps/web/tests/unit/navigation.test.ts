import { existsSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

import { PORTAL_PATHS, ROLES } from "@/lib/auth/roles";
import { activeHref, NAVIGATION } from "@/lib/navigation";

const APP = path.resolve(import.meta.dirname, "../../src/app");

/** Route groups are folders like (student); find a page file for a URL path. */
function pageExists(urlPath: string): boolean {
  const groups = ["", "(student)", "(therapist)", "(teacher)", "(admin)", "(auth)", "(public)"];
  return groups.some((g) => existsSync(path.join(APP, g, urlPath, "page.tsx")));
}

describe("navigation", () => {
  it("has a menu for every role, starting with the overview", () => {
    for (const role of ROLES) {
      expect(NAVIGATION[role][0]?.href).toBe(PORTAL_PATHS[role]);
    }
  });

  it("keeps every role inside its own portal", () => {
    for (const role of ROLES) {
      for (const item of NAVIGATION[role]) {
        expect(
          item.href === PORTAL_PATHS[role] || item.href.startsWith(`${PORTAL_PATHS[role]}/`),
        ).toBe(true);
      }
    }
  });

  it("only links to pages that exist (unbuilt ones are marked soon)", () => {
    for (const role of ROLES) {
      for (const item of NAVIGATION[role]) {
        if (item.soon)
          expect(pageExists(item.href), `${item.href} now exists: drop 'soon'`).toBe(false);
        else expect(pageExists(item.href), `${item.href} is missing`).toBe(true);
      }
    }
  });

  it("every portal has the full set of route files", () => {
    const names: Record<string, string> = {
      student: "(student)",
      therapist: "(therapist)",
      teacher: "(teacher)",
      administrator: "(admin)",
    };
    for (const role of ROLES) {
      const dir = path.join(APP, names[role] as string, PORTAL_PATHS[role]);
      for (const file of [
        "layout.tsx",
        "page.tsx",
        "loading.tsx",
        "error.tsx",
        "account/page.tsx",
      ]) {
        expect(existsSync(path.join(dir, file)), `${PORTAL_PATHS[role]}/${file}`).toBe(true);
      }
    }
  });

  it("picks the most specific active item", () => {
    const items = NAVIGATION.student;
    expect(activeHref(items, "/student")).toBe("/student");
    expect(activeHref(items, "/student/account")).toBe("/student/account");
    expect(activeHref(items, "/student/account/security")).toBe("/student/account");
    expect(activeHref(items, "/student/check-in")).toBe("/student/check-in");
    expect(activeHref(items, "/student/therapists/abc")).toBe("/student/therapists");
    expect(activeHref(items, "/student/privacy/consent")).toBe("/student/privacy");
    expect(activeHref(items, "/help")).toBeNull();
  });

  it("keeps the parent item active on pages that belong under it", () => {
    const items = NAVIGATION.student;
    for (const path of ["mood", "stress", "sleep", "assessment", "trends"]) {
      expect(activeHref(items, `/student/${path}`)).toBe("/student/wellness");
    }
  });

  it("never highlights an unbuilt item", () => {
    expect(activeHref(NAVIGATION.teacher, "/teacher/insights")).toBe("/teacher");
  });
});
