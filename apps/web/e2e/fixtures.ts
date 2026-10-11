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
  therapist_id: string;
  care_student: string;
  care_student_id: string;
  care_student_name: string;
  pending_therapist: string;
  /** A student no other test uses: a crisis check-in pauses their suggestions. */
  crisis_student: string;
  /** Set for the teacher portal: a class the teacher teaches and a student enrolled in it. */
  teacher_course_code: string;
  teacher_course_title: string;
  teacher_student_name: string;
  teacher_full_name: string;
} = JSON.parse(readFileSync(path.resolve(import.meta.dirname, ".auth/users.json"), "utf8"));
const password = process.env.E2E_PASSWORD ?? "";

export const credentials = (role: Role) => ({ email: users[role], password });
export const careStudentName = users.care_student_name;
/** The verified therapist and the student on their care team (both signed in by some tests). */
export const carePair = {
  therapistId: users.therapist_id,
  studentEmail: users.care_student,
  studentId: users.care_student_id,
  studentName: users.care_student_name,
};
export const pendingTherapistEmail = users.pending_therapist;
export const crisisStudentEmail = users.crisis_student;
export const teacherCourse = {
  code: users.teacher_course_code,
  title: users.teacher_course_title,
  studentName: users.teacher_student_name,
  teacherName: users.teacher_full_name,
};

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

export async function open(page: Page, path: string, heading: RegExp) {
  await page.goto(path);
  await expect(page.getByRole("heading", { level: 1, name: heading })).toBeVisible();
}

/** Waits until nothing on the page is still loading its data. */
export async function settled(page: Page) {
  await expect(page.getByText(/^Loading/)).toHaveCount(0);
  await expect(page.locator("[data-slot=skeleton]")).toHaveCount(0);
}

export { expect };
