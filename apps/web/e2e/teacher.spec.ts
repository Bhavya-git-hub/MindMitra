import AxeBuilder from "@axe-core/playwright";

import { expect, HEADING, open, settled, signInAndWait, teacherCourse, test } from "./fixtures";

/** Every teacher page that does not need a particular id. */
const TEACHER_PAGES: [path: string, heading: RegExp][] = [
  ["/teacher", /^Welcome, /],
  ["/teacher/classes", /^Class analytics$/],
  ["/teacher/trends", /^Wellness trends$/],
  ["/teacher/referrals", /^Referrals$/],
  ["/teacher/referrals/new", /^Refer a student$/],
  ["/teacher/support-requests", /^Student requests$/],
  ["/teacher/resources", /^Resources for staff$/],
  ["/teacher/account", /^Account$/],
];

const REQUEST_MESSAGE = "Synthetic e2e request: could I have two more days?";

test.describe("teacher portal (real API)", () => {
  test("the dashboard shows group counts and what teachers can never see", async ({ page }) => {
    await signInAndWait(page, "teacher");
    await settled(page);
    for (const label of ["Your classes", "Open referrals", "Student requests"]) {
      await expect(page.getByText(label, { exact: true }).first()).toBeVisible();
    }
    await expect(page.getByText(/never shown to teachers/)).toBeVisible();
    const nav = page.getByRole("navigation", { name: "Teacher navigation" });
    for (const name of [
      "Classes",
      "Wellness trends",
      "Referrals",
      "Student requests",
      "Resources",
    ]) {
      await expect(nav.getByRole("link", { name })).toBeVisible();
    }
  });

  test("a class shows group figures, or says why it cannot, and never names a student", async ({
    page,
  }) => {
    await signInAndWait(page, "teacher");
    await open(page, "/teacher/classes", /^Class analytics$/);
    await settled(page);
    await page.getByRole("link", { name: teacherCourse.title }).first().click();
    await expect(page.getByRole("heading", { level: 1, name: teacherCourse.title })).toBeVisible();
    await settled(page);
    await expect(
      page
        .getByText(/Supportive next steps|Wellness trends|Not enough students to show this group/)
        .first(),
    ).toBeVisible();
    const requests: string[] = [];
    page.on("request", (r) => {
      if (r.url().includes("/analytics")) requests.push(r.url());
    });
    await page.getByRole("button", { name: "12 weeks" }).click();
    await expect.poll(() => requests.some((u) => u.includes("weeks=12"))).toBe(true);
    await settled(page);
    const text = (await page.locator("main").innerText()).toLowerCase();
    expect(text).not.toContain(teacherCourse.studentName.toLowerCase());
  });

  test("the department trends page offers a printable report and a CSV", async ({ page }) => {
    await signInAndWait(page, "teacher");
    await open(page, "/teacher/trends", /^Wellness trends$/);
    await settled(page);
    await expect(page.getByText(/own department only/)).toBeVisible();
    await expect(page.getByRole("button", { name: "Print report" })).toBeVisible();
    const download = page.waitForEvent("download");
    await page.getByRole("button", { name: /Download CSV/ }).click();
    const file = await download;
    expect(file.suggestedFilename()).toMatch(/anonymous-wellbeing-report.*\.csv$/);
  });

  test("a referral can be sent, shows only a status, and cannot be doubled up", async ({
    page,
  }) => {
    await signInAndWait(page, "teacher");
    await open(page, "/teacher/referrals/new", /^Refer a student$/);
    await settled(page);
    await page.getByRole("button", { name: "Send referral" }).click();
    await expect(page.getByText("Choose a class.")).toBeVisible();

    await page
      .getByLabel("Class")
      .selectOption({ label: `${teacherCourse.code} ${teacherCourse.title}` });
    await page.getByLabel("Student").selectOption({ label: teacherCourse.studentName });
    await page.getByLabel("What have you noticed?").selectOption("academic_distress");
    await page.getByLabel(/What you have seen/).fill("Synthetic e2e note: has missed two classes.");
    await page.getByRole("button", { name: "Send referral" }).click();
    await expect(page).toHaveURL(/\/teacher\/referrals\/[0-9a-f-]{36}$/);
    await expect(page.getByText("Received by the wellbeing team").first()).toBeVisible();
    await expect(page.getByText(/handles referrals in confidence/)).toBeVisible();

    await open(page, "/teacher/referrals", /^Referrals$/);
    await settled(page);
    await expect(page.getByRole("link", { name: teacherCourse.studentName }).first()).toBeVisible();

    await open(page, "/teacher/referrals/new", /^Refer a student$/);
    await settled(page);
    await page
      .getByLabel("Class")
      .selectOption({ label: `${teacherCourse.code} ${teacherCourse.title}` });
    await page.getByLabel("Student").selectOption({ label: teacherCourse.studentName });
    await page.getByLabel("What have you noticed?").selectOption("wellbeing_concern");
    await page.getByRole("button", { name: "Send referral" }).click();
    await expect(page.getByText(/already have an open referral/)).toBeVisible();
  });

  test("a student can ask a teacher for help, and the teacher sees only that message", async ({
    page,
    browser,
  }) => {
    await signInAndWait(page, "student");
    await open(page, "/student/teacher-support", /^Ask a teacher$/);
    await settled(page);
    await expect(page.getByText(/can never see your check-ins, journal/)).toBeVisible();
    await page
      .getByLabel("Class")
      .selectOption({ label: `${teacherCourse.code} ${teacherCourse.title}` });
    const teacherOption = page
      .getByLabel("Teacher")
      .locator("option", { hasText: teacherCourse.teacherName });
    await page
      .getByLabel("Teacher")
      .selectOption({ value: (await teacherOption.getAttribute("value")) ?? "" });
    await page.getByLabel("What would help?").selectOption("extension");
    await page.getByLabel(/A few words/).fill(REQUEST_MESSAGE);
    await page.getByRole("button", { name: "Send to my teacher" }).click();
    await expect(page.getByText("Sent. Your teacher will see it soon.")).toBeVisible();
    await expect(page.getByText(REQUEST_MESSAGE)).toBeVisible();

    const teacher = await (await browser.newContext()).newPage();
    await signInAndWait(teacher, "teacher");
    await open(teacher, "/teacher/support-requests", /^Student requests$/);
    await settled(teacher);
    await expect(teacher.getByText(REQUEST_MESSAGE)).toBeVisible();
    await teacher.getByRole("button", { name: "I've seen this" }).first().click();
    await expect(teacher.getByText("Seen", { exact: true }).first()).toBeVisible();
    await teacher.context().close();

    await page.reload();
    await settled(page);
    await page.getByRole("button", { name: "Withdraw" }).first().click();
    await expect(page.getByText("Withdrawn by the student").first()).toBeVisible();
  });

  test("the staff resource library opens a guide", async ({ page }) => {
    await signInAndWait(page, "teacher");
    await open(page, "/teacher/resources", /^Resources for staff$/);
    await settled(page);
    await page
      .getByRole("link", { name: /refer a student to the wellbeing team/i })
      .first()
      .click();
    await expect(page.getByRole("heading", { level: 1 })).toContainText(/refer a student/i);
  });

  test("students and therapists never see the staff library or teacher pages", async ({ page }) => {
    await signInAndWait(page, "student");
    for (const path of ["/teacher", "/teacher/classes", "/teacher/resources"]) {
      await page.goto(path);
      await expect(page).toHaveURL(/\/student$/);
      // Let the session refresh finish before the next full page load, or the old cookie is reused.
      await expect(page.getByRole("heading", { level: 1 })).toHaveText(HEADING.student);
      await settled(page);
    }
    await open(page, "/student/resources", /^Resources$/);
    await settled(page);
    await expect(page.getByText(/refer a student to the wellbeing team/i)).toHaveCount(0);
  });

  test("a malformed id is a 404, not an API call", async ({ page }) => {
    await signInAndWait(page, "teacher");
    const calls: string[] = [];
    page.on("request", (r) => {
      if (r.url().includes("/api/v1/teacher/classes/")) calls.push(r.url());
    });
    await page.goto("/teacher/classes/not-a-uuid");
    await expect(page.getByRole("heading", { level: 1, name: /find that page/ })).toBeVisible();
    expect(calls).toEqual([]);
  });
});

test.describe("teacher pages: layout and accessibility", () => {
  test.describe("at 320px there is no horizontal scrolling", () => {
    test.use({ viewport: { width: 320, height: 640 } });
    test("every teacher page", async ({ page }) => {
      test.setTimeout(120_000);
      await signInAndWait(page, "teacher");
      for (const [path, heading] of TEACHER_PAGES) {
        await open(page, path, heading);
        await settled(page);
        const overflow = await page.evaluate(
          () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
        );
        const offenders =
          overflow > 0
            ? await page.evaluate(() =>
                [...document.querySelectorAll("body *")]
                  .filter(
                    (e) => e.getBoundingClientRect().right > document.documentElement.clientWidth,
                  )
                  .slice(0, 8)
                  .map((e) => `${e.tagName.toLowerCase()}.${String(e.className).slice(0, 80)}`),
              )
            : [];
        expect(overflow, `${path} overflows: ${offenders.join(" | ")}`).toBeLessThanOrEqual(0);
      }
    });
  });

  for (const scheme of ["light", "dark"] as const) {
    test.describe(`axe in ${scheme} mode`, () => {
      test.use({ colorScheme: scheme });
      test("every teacher page", async ({ page }) => {
        test.setTimeout(180_000);
        await signInAndWait(page, "teacher");
        for (const [path, heading] of TEACHER_PAGES) {
          await open(page, path, heading);
          await settled(page);
          const results = await new AxeBuilder({ page })
            .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
            .analyze();
          const summary = results.violations.map(
            (v) =>
              `${v.id} (${v.impact}): ${v.help}\n${v.nodes.map((n) => `  ${n.target.join(" ")}  ${n.failureSummary?.split("\n")[1] ?? ""}`).join("\n")}`,
          );
          expect(summary, `${path}\n${summary.join("\n")}`).toEqual([]);
        }
      });
    });
  }
});
