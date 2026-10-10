import { expect, test as base, type Page } from "@playwright/test";
import { readFileSync } from "node:fs";
import path from "node:path";

export type Role = "student" | "therapist" | "teacher" | "administrator";
export const ROLES: Role[] = ["student", "therapist", "teacher", "administrator"];
export const PORTAL: Record<Role, string> = {
  student: "/student",
  therapist: "/therapist",
  teacher: "/teacher",
  administrator: "/admin",
};
export const HEADING: Record<Role, RegExp> = {
  student: /Hello, /,
  therapist: /Welcome, /,
  teacher: /Welcome, /,
  administrator: /Welcome, /,
};

const users: Record<Role, string> & {
  /** Set by scripts/e2e/prepare_backend.py for the therapist portal. */
  care_student_name: string;
  pending_therapist: string;
} = JSON.parse(readFileSync(path.resolve(import.meta.dirname, ".auth/users.json"), "utf8"));
const password = process.env.E2E_PASSWORD ?? "";

export const credentials = (role: Role) => ({ email: users[role], password });
export const careStudentName = users.care_student_name;
export const pendingTherapistEmail = users.pending_therapist;

export async function signIn(page: Page, role: Role, next?: string, email?: string) {
  const { email: roleEmail, password } = credentials(role);
  email ??= roleEmail;
  await page.goto(next ? `/login?next=${encodeURIComponent(next)}` : "/login");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password", { exact: true }).fill(password);
  await page.getByRole("button", { name: "Sign in" }).click();
}

export async function signInAndWait(page: Page, role: Role) {
  await signIn(page, role);
  await page.waitForURL(`**${PORTAL[role]}`);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(HEADING[role]);
}

/** Fails the test on uncaught exceptions and on Content-Security-Policy violations. */
export const test = base.extend<{ guard: void }>({
  guard: [
    async ({ page }, use) => {
      const problems: string[] = [];
      page.on("pageerror", (e) => problems.push(`pageerror: ${e.message}`));
      page.on("console", (m) => {
        const text = m.text();
        if (m.type() === "error" && /Content Security Policy|hydrat/i.test(text)) {
          problems.push(`console: ${text}`);
        }
      });
      await use();
      expect(problems, problems.join("\n")).toEqual([]);
    },
    { auto: true },
  ],
});

export { expect };
