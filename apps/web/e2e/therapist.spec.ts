import AxeBuilder from "@axe-core/playwright";

import {
  careStudentName,
  expect,
  open,
  pendingTherapistEmail,
  settled,
  signIn,
  signInAndWait,
  test,
} from "./fixtures";

/** Every therapist page that does not need a particular id. */
const THERAPIST_PAGES: [path: string, heading: RegExp][] = [
  ["/therapist", /^Welcome, /],
  ["/therapist/students", /^My students$/],
  ["/therapist/appointments", /^Appointments$/],
  ["/therapist/availability", /^Availability$/],
  ["/therapist/sessions", /^Sessions$/],
  ["/therapist/alerts", /^Risk alerts$/],
  ["/therapist/follow-ups", /^Follow-ups$/],
  ["/therapist/messages", /^Messages$/],
  ["/therapist/profile", /^Profile$/],
  ["/therapist/account", /^Account$/],
];

const NOTE = "Synthetic e2e note: practised paced breathing together.";

test.describe("therapist portal (real API)", () => {
  test("the dashboard shows the therapist's day, status and counts", async ({ page }) => {
    await signInAndWait(page, "therapist");
    await settled(page);
    await expect(page.getByText("Verified", { exact: true }).first()).toBeVisible();
    for (const label of ["Requests waiting", "Open alerts", "Follow-ups due", "Caseload"]) {
      await expect(page.getByText(label, { exact: true }).first()).toBeVisible();
    }
    await expect(page.getByRole("heading", { name: "Today" })).toBeVisible();
    const nav = page.getByRole("navigation", { name: "Therapist navigation" });
    for (const name of ["My students", "Appointments", "Sessions", "Risk alerts", "Messages"]) {
      await expect(nav.getByRole("link", { name })).toBeVisible();
    }
  });

  test("the caseload lists a student, whose profile says what they have shared", async ({
    page,
  }) => {
    await signInAndWait(page, "therapist");
    await open(page, "/therapist/students", /^My students$/);
    await settled(page);
    await page.getByRole("link", { name: careStudentName }).first().click();
    await expect(page.getByRole("heading", { level: 1, name: careStudentName })).toBeVisible();
    await expect(page.getByText("What you can see")).toBeVisible();
    await expect(page.getByRole("heading", { name: "Appointments with you" })).toBeVisible();
  });

  test("a session can be started, a private note saved twice, and the versions read back", async ({
    page,
  }) => {
    await signInAndWait(page, "therapist");
    await open(page, "/therapist/appointments", /^Appointments$/);
    await page.getByRole("button", { name: "Upcoming" }).click();
    await settled(page);
    await page.getByRole("button", { name: "Start session" }).first().click();
    await expect(page).toHaveURL(/\/therapist\/sessions\/[0-9a-f-]{36}$/);
    await expect(page.getByText("Only you can read this")).toBeVisible();

    await page.getByLabel("Your note").fill(NOTE);
    await page.getByRole("button", { name: "Save note" }).click();
    await expect(page.getByText("Note saved")).toBeVisible();

    await page.getByLabel("Your note").fill(`${NOTE} Second visit.`);
    await page.getByRole("button", { name: "Save note" }).click();
    await expect(page.getByText(/Version 2, saved/)).toBeVisible();

    // The note text never appears in the page URL, and is not kept in browser storage.
    expect(page.url()).not.toContain("Synthetic");
    const stored = await page.evaluate(
      () => JSON.stringify({ ...localStorage }) + JSON.stringify({ ...sessionStorage }),
    );
    expect(stored).not.toContain("Synthetic");

    await page.getByRole("button", { name: /View version 1/ }).click();
    await expect(page.getByText("Version 1 (read only)")).toBeVisible();
    await expect(page.getByText(NOTE, { exact: true })).toBeVisible();

    await page.getByRole("button", { name: "Complete session" }).first().click();
    await page.getByRole("alertdialog").getByRole("button", { name: "Complete session" }).click();
    await expect(page.getByText("Session completed")).toBeVisible();
  });

  test("availability can be added and removed", async ({ page }) => {
    await signInAndWait(page, "therapist");
    await open(page, "/therapist/availability", /^Availability$/);
    await settled(page);
    const day = new Date(Date.now() + 40 * 86_400_000).toISOString().slice(0, 10);
    await page.getByLabel("Date").fill(day);
    await page.getByLabel("Starts at").fill("16:10");
    await page.getByRole("button", { name: "Add availability" }).click();
    await expect(page.getByText("Time added")).toBeVisible();
    await page
      .getByRole("button", { name: /^Remove .*4:10/ })
      .first()
      .click();
    await page.getByRole("alertdialog").getByRole("button", { name: "Remove time" }).click();
    await expect(page.getByText(/Time removed/)).toBeVisible();
  });

  test("a follow-up can be added for a student and marked done", async ({ page }) => {
    await signInAndWait(page, "therapist");
    await open(page, "/therapist/follow-ups", /^Follow-ups$/);
    await settled(page);
    const due = new Date(Date.now() + 3 * 86_400_000).toISOString().slice(0, 10);
    await page.getByLabel("Student").selectOption({ label: careStudentName });
    await page.getByLabel("Due on").fill(due);
    await page.getByLabel(/Reminder for yourself/).fill("Synthetic e2e reminder");
    await page.getByRole("button", { name: "Add follow-up" }).click();
    await expect(page.getByText("Follow-up added")).toBeVisible();
    await page.getByRole("button", { name: "Mark done" }).first().click();
  });

  test("messages and alerts open without errors", async ({ page }) => {
    await signInAndWait(page, "therapist");
    await open(page, "/therapist/messages", /^Messages$/);
    await settled(page);
    await expect(
      page.getByRole("heading", { name: /Conversations|No conversations yet/ }),
    ).toBeVisible();
    await open(page, "/therapist/alerts", /^Risk alerts$/);
    await settled(page);
    await expect(
      page.getByRole("heading", { name: /Needs a person|No open alerts/ }),
    ).toBeVisible();
  });

  test("a malformed id is a 404, not an API call", async ({ page }) => {
    await signInAndWait(page, "therapist");
    const calls: string[] = [];
    page.on("request", (r) => {
      if (r.url().includes("/api/v1/therapist/students/")) calls.push(r.url());
    });
    await page.goto("/therapist/students/not-a-uuid");
    await expect(page.getByRole("heading", { level: 1, name: /find that page/ })).toBeVisible();
    expect(calls).toEqual([]);
  });

  test("students cannot open the therapist portal or its notes", async ({ page }) => {
    await signInAndWait(page, "student");
    for (const path of ["/therapist/sessions", "/therapist/students"]) {
      await page.goto(path);
      await expect(page).toHaveURL(/\/student$/);
    }
  });

  test("a therapist waiting for verification sees no students and is told why", async ({
    page,
  }) => {
    await signIn(page, "therapist", undefined, pendingTherapistEmail);
    await page.waitForURL("**/therapist");
    await open(page, "/therapist/students", /^My students$/);
    await expect(page.getByText(/once an administrator has verified/)).toBeVisible();
    await open(page, "/therapist/sessions", /^Sessions$/);
    await expect(page.getByText(/once an administrator has verified/)).toBeVisible();
    await open(page, "/therapist/profile", /^Profile$/);
    await expect(page.getByText("Waiting for verification").first()).toBeVisible();
  });
});

test.describe("therapist pages: layout and accessibility", () => {
  test.describe("at 320px there is no horizontal scrolling", () => {
    test.use({ viewport: { width: 320, height: 640 } });
    test("every therapist page", async ({ page }) => {
      test.setTimeout(120_000);
      await signInAndWait(page, "therapist");
      for (const [path, heading] of THERAPIST_PAGES) {
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
      test("every therapist page", async ({ page }) => {
        test.setTimeout(180_000);
        await signInAndWait(page, "therapist");
        for (const [path, heading] of THERAPIST_PAGES) {
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
