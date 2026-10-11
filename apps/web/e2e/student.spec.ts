import AxeBuilder from "@axe-core/playwright";

import { expect, open, settled, signInAndWait, test } from "./fixtures";

/** Every page a student can open without needing a particular id. */
const STUDENT_PAGES: [path: string, heading: RegExp][] = [
  ["/student", /^Hello, /],
  ["/student/check-in", /^Daily check-in$/],
  ["/student/wellness", /^Wellness$/],
  ["/student/mood", /^Mood$/],
  ["/student/stress", /^Stress$/],
  ["/student/sleep", /^Sleep$/],
  ["/student/assessment", /^Wellbeing check$/],
  ["/student/trends", /^Your trends$/],
  ["/student/goals", /^Goals$/],
  ["/student/recommendations", /^Suggestions$/],
  ["/student/assistant", /^Companion$/],
  ["/student/therapists", /^Find a therapist$/],
  ["/student/appointments", /^Appointments$/],
  ["/student/messages", /^Messages$/],
  ["/student/resources", /^Resources$/],
  ["/student/privacy", /^Privacy$/],
  ["/student/privacy/consent", /^Consent$/],
  ["/student/emergency", /^Urgent support$/],
];

test.describe("student portal (real API)", () => {
  test("the dashboard shows the check-in, indicators, appointment, trends and ideas", async ({
    page,
  }) => {
    await signInAndWait(page, "student");
    await settled(page);
    await expect(page.getByRole("heading", { name: "How things look" })).toBeVisible();
    for (const label of ["Mood", "Stress", "Sleep", "Wellbeing check"]) {
      await expect(page.getByText(label, { exact: true }).first()).toBeVisible();
    }
    await expect(page.getByRole("heading", { name: "This week" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Ideas for you" })).toBeVisible();
    await expect(page.getByRole("link", { name: /^Get help/ }).first()).toBeVisible();
  });

  test("a daily check-in is saved and shows on the dashboard", async ({ page }) => {
    await signInAndWait(page, "student");
    await open(page, "/student/check-in", /^Daily check-in$/);

    // Required field first: submitting without a mood explains what to do.
    await page.getByRole("button", { name: /Save check-in/ }).click();
    await expect(page.getByRole("alert").filter({ hasText: /feeling/ })).toBeVisible();

    await page
      .getByRole("group", { name: "Mood", exact: true })
      .getByLabel("Good")
      .check({ force: true });
    await page.getByRole("button", { name: "calm" }).click();
    await page
      .getByRole("group", { name: "How stressed do you feel?" })
      .locator("label")
      .nth(1)
      .click();
    await page.getByRole("button", { name: /Save check-in/ }).click();

    await expect(
      page.getByRole("heading", { level: 1, name: "Thanks for checking in" }),
    ).toBeVisible();
    await page.getByRole("link", { name: "Back to my dashboard" }).click();
    await expect(page.getByRole("heading", { level: 1, name: /^Hello, / })).toBeVisible();
    await settled(page);
    await expect(page.getByText("Checked in today", { exact: false }).first()).toBeVisible();
  });

  test("a mood entry can be logged on its own", async ({ page }) => {
    await signInAndWait(page, "student");
    await open(page, "/student/mood", /^Mood$/);
    await page
      .getByRole("group", { name: "How are you feeling?" })
      .getByLabel("Okay")
      .check({ force: true });
    await page.getByRole("button", { name: "Log mood" }).click();
    await expect(page.getByText("Mood logged")).toBeVisible();
    await expect(page.getByRole("heading", { name: "Recent entries" })).toBeVisible();
    await expect(page.getByText(/3 of 5, Okay/).first()).toBeVisible();
  });

  test("the wellbeing check asks every question and gives a gentle result", async ({ page }) => {
    await signInAndWait(page, "student");
    await open(page, "/student/assessment", /^Wellbeing check$/);
    await page.getByRole("button", { name: "See my result" }).click();
    await expect(page.getByText("Please answer every question")).toBeVisible();
    for (const group of await page.getByRole("group").all()) {
      await group.locator("label").nth(3).click();
    }
    await page.getByRole("button", { name: "See my result" }).click();
    await expect(page.getByRole("heading", { name: "Your result" })).toBeVisible();
    await expect(page.getByText(/not a diagnosis/i)).toBeVisible();
  });

  test("a goal can be added, progressed and finished", async ({ page }) => {
    await signInAndWait(page, "student");
    await open(page, "/student/goals", /^Goals$/);
    const title = `Walk after lunch ${Date.now()}`;
    await page.getByLabel("What would you like to work on?").fill(title);
    await page.getByLabel("Target number (optional)").fill("5");
    await page.getByLabel("Measured in (optional)").fill("walks");
    await page.getByRole("button", { name: "Add goal" }).click();
    const card = page.getByRole("listitem").filter({ hasText: title });
    await expect(card).toBeVisible();
    await card.getByLabel(/Progress so far/).fill("2");
    await card.getByRole("button", { name: "Save progress" }).click();
    await expect(card.getByText(/2 of 5 walks \(40%\)/)).toBeVisible();
    await card.getByRole("button", { name: "Mark as done" }).click();
    await expect(page.getByRole("heading", { name: "Finished" })).toBeVisible();
  });

  test("a therapist can be found, a time requested, and the request cancelled", async ({
    page,
  }) => {
    await signInAndWait(page, "student");
    await open(page, "/student/therapists", /^Find a therapist$/);
    await settled(page);
    await page.getByRole("link", { name: "View profile" }).first().click();
    await expect(page.getByRole("heading", { name: "Available times" })).toBeVisible();
    await settled(page);

    const times = page.getByRole("button", { name: /, \d{1,2}:\d{2}/ });
    test.skip((await times.count()) === 0, "the seed has no open times for this therapist");
    await times.first().click();
    const dialog = page.getByRole("dialog", { name: "Request this appointment" });
    await dialog
      .getByLabel(/What would you like to talk about/)
      .fill("Feeling stretched before exams");
    await dialog.getByRole("button", { name: "Send request" }).click();
    await expect(page.getByText("Request sent").first()).toBeVisible();

    await page.getByRole("link", { name: "See your appointments" }).click();
    await expect(page.getByRole("heading", { level: 1, name: "Appointments" })).toBeVisible();
    await expect(page.getByText("Feeling stretched before exams").first()).toBeVisible();
    await expect(page.getByText("Waiting for confirmation").first()).toBeVisible();

    await page.getByRole("button", { name: "Cancel" }).first().click();
    await page.getByRole("alertdialog").getByRole("button", { name: "Cancel appointment" }).click();
    await expect(page.getByText("Appointment cancelled")).toBeVisible();
  });

  test("consent can be switched off and on, and the required one cannot", async ({ page }) => {
    await signInAndWait(page, "student");
    await open(page, "/student/privacy/consent", /^Consent$/);
    await expect(page.getByText("Required").first()).toBeVisible();
    const toggle = page.getByRole("switch", { name: /Share my mood check-ins/ });
    const before = await toggle.getAttribute("aria-checked");
    await toggle.click();
    await expect(toggle).toHaveAttribute("aria-checked", before === "true" ? "false" : "true");
    await page.reload();
    await expect(page.getByRole("switch", { name: /Share my mood check-ins/ })).toHaveAttribute(
      "aria-checked",
      before === "true" ? "false" : "true",
    );
    await page.getByRole("switch", { name: /Share my mood check-ins/ }).click();
    await expect(page.getByRole("switch", { name: /Share my mood check-ins/ })).toHaveAttribute(
      "aria-checked",
      before ?? "false",
    );
  });

  test("the data export downloads as a file", async ({ page }) => {
    await signInAndWait(page, "student");
    await open(page, "/student/privacy", /^Privacy$/);
    const download = page.waitForEvent("download");
    await page.getByRole("button", { name: "Download my data" }).click();
    expect((await download).suggestedFilename()).toMatch(/^mindmitra-my-data-.*\.json$/);
  });

  test("urgent support lists contacts and lets the student ask for a person", async ({ page }) => {
    await signInAndWait(page, "student");
    await open(page, "/student/emergency", /^Urgent support$/);
    await settled(page);
    await expect(page.getByText(/immediate danger/)).toBeVisible();
    await expect(page.getByRole("link", { name: /^Call / }).first()).toBeVisible();
    await page.getByLabel(/Anything you'd like them to know/).fill("Having a hard week");
    await page.getByRole("button", { name: "Ask someone to reach out" }).click();
    await expect(page.getByText("Your request is in")).toBeVisible();
  });

  test("resources can be searched and opened", async ({ page }) => {
    await signInAndWait(page, "student");
    await open(page, "/student/resources", /^Resources$/);
    await settled(page);
    const first = page.getByRole("main").getByRole("list").getByRole("link").first();
    const title = (await first.textContent()) ?? "";
    await first.click();
    await expect(page.getByRole("heading", { level: 1, name: title })).toBeVisible();
  });

  test("messages explain when there are no conversations yet", async ({ page }) => {
    await signInAndWait(page, "student");
    await open(page, "/student/messages", /^Messages$/);
    await settled(page);
    await expect(
      page.getByRole("heading", { name: /Conversations|No conversations yet/ }),
    ).toBeVisible();
  });

  test("a suggestion can be marked helpful, and the answer taken back", async ({ page }) => {
    await signInAndWait(page, "student");
    await open(page, "/student/recommendations", /^Suggestions$/);
    await settled(page);
    // The database is shared between runs, so start from "no answer" whatever was saved before.
    const helpful = page.getByRole("button", { name: "Helpful", exact: true }).first();
    await expect(helpful).toBeVisible();
    if ((await helpful.getAttribute("aria-pressed")) === "true") {
      await helpful.click();
      await expect(helpful).toHaveAttribute("aria-pressed", "false");
    }
    await helpful.click();
    await expect(helpful).toHaveAttribute("aria-pressed", "true");
    await helpful.click();
    await expect(helpful).toHaveAttribute("aria-pressed", "false");
  });

  test("a malformed id is a 404, not an API call", async ({ page }) => {
    await signInAndWait(page, "student");
    const calls: string[] = [];
    page.on("request", (r) => {
      if (r.url().includes("/api/v1/therapists/")) calls.push(r.url());
    });
    await page.goto("/student/therapists/not-a-uuid");
    await expect(page.getByRole("heading", { level: 1, name: /find that page/ })).toBeVisible();
    expect(calls).toEqual([]);
  });

  test("other portals are closed to students", async ({ page }) => {
    await signInAndWait(page, "student");
    await page.goto("/therapist");
    await expect(page).toHaveURL(/\/student$/);
  });
});

test.describe("student pages: layout and accessibility", () => {
  test.describe("at 320px there is no horizontal scrolling", () => {
    test.use({ viewport: { width: 320, height: 640 } });
    test("every student page", async ({ page }) => {
      test.setTimeout(120_000);
      await signInAndWait(page, "student");
      for (const [path, heading] of STUDENT_PAGES) {
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
      test("every student page", async ({ page }) => {
        test.setTimeout(180_000);
        await signInAndWait(page, "student");
        for (const [path, heading] of STUDENT_PAGES) {
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
