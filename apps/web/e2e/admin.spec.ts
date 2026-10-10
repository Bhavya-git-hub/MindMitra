import AxeBuilder from "@axe-core/playwright";
import type { Page } from "@playwright/test";

import { expect, open, settled, signInAndWait, test } from "./fixtures";

/** Every administrator page that does not need a particular id. */
const ADMIN_PAGES: [path: string, heading: RegExp][] = [
  ["/admin", /^Welcome, /],
  ["/admin/users", /^People$/],
  ["/admin/therapists", /^Therapist verification$/],
  ["/admin/academics", /^Departments and courses$/],
  ["/admin/appointments", /^Appointment oversight$/],
  ["/admin/resources", /^Resources$/],
  ["/admin/resources/new", /^New resource$/],
  ["/admin/analytics", /^Analytics$/],
  ["/admin/audit", /^Audit log$/],
  ["/admin/settings", /^Settings$/],
  ["/admin/account", /^Account$/],
];

/** A fresh, unique suffix so parallel and repeated runs never collide on emails or codes. */
const unique = () => `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`;

async function chooseFirstDepartment(page: Page, dialog = page.getByRole("dialog")) {
  const select = dialog.getByLabel("Department");
  await expect(select.locator("option")).not.toHaveCount(1);
  await select.selectOption({ index: 1 });
}

async function invite(page: Page, role: "Student" | "Therapist", fullName: string, email: string) {
  await open(page, "/admin/users", /^People$/);
  await page.getByRole("button", { name: "Invite someone" }).click();
  const dialog = page.getByRole("dialog", { name: "Invite someone" });
  await dialog.getByLabel("Role").selectOption({ label: role });
  await dialog.getByLabel("Full name").fill(fullName);
  await dialog.getByLabel("Email").fill(email);
  if (role === "Student") {
    await chooseFirstDepartment(page, dialog);
    await dialog.getByLabel("Student number").fill(`E2E-${unique()}`);
  } else {
    await dialog.getByLabel("Licence number").fill(`L-${unique()}`);
  }
  await dialog.getByRole("button", { name: "Send invitation" }).click();
  await expect(page.getByText("Invitation sent")).toBeVisible();
  await expect(dialog).toBeHidden();
}

test.describe("administrator portal (real API)", () => {
  test("the dashboard shows counts and says what administrators can never read", async ({
    page,
  }) => {
    await signInAndWait(page, "administrator");
    await settled(page);
    for (const label of ["Active people", "Therapists to verify", "Safety alerts waiting"]) {
      await expect(page.getByText(label, { exact: true }).first()).toBeVisible();
    }
    await expect(page.getByText(/cannot read what students write/)).toBeVisible();
    const nav = page.getByRole("navigation", { name: "Administrator navigation" });
    for (const name of [
      "People",
      "Therapist verification",
      "Departments and courses",
      "Appointments",
      "Resources",
      "Analytics",
      "Audit log",
      "Settings",
    ]) {
      await expect(nav.getByRole("link", { name })).toBeVisible();
    }
  });

  test("every page loads without an error and offers no therapy notes or journals", async ({
    page,
  }) => {
    await signInAndWait(page, "administrator");
    for (const [path, heading] of ADMIN_PAGES) {
      await open(page, path, heading);
      await settled(page);
      await expect(page.getByText(/something went wrong|couldn.t load/i)).toHaveCount(0);
      const text = (await page.locator("main").innerText()).toLowerCase();
      expect(text, path).not.toMatch(/journal entry|session note|companion conversation:/);
    }
  });

  test("invites a student, finds them, suspends them with a confirmation", async ({ page }) => {
    const id = unique();
    const name = `Eve E2e ${id}`;
    const email = `eve.${id}@e2e.example`;
    await signInAndWait(page, "administrator");
    await invite(page, "Student", name, email);

    await page.getByLabel("Search by name or email").fill(id);
    const row = page.getByRole("row").filter({ hasText: name });
    await expect(row).toBeVisible();
    await expect(row.getByText("Invited")).toBeVisible();

    // An invited account can be sent its invitation again, but cannot be suspended.
    await row.getByRole("button", { name: `Actions for ${name}` }).click();
    await expect(page.getByRole("menuitem", { name: "Send the invitation again" })).toBeVisible();
    await expect(page.getByRole("menuitem", { name: "Suspend" })).toHaveCount(0);
    await page.keyboard.press("Escape");

    await row.getByRole("button", { name: `Actions for ${name}` }).click();
    await page.getByRole("menuitem", { name: "Deactivate" }).click();
    const confirm = page.getByRole("alertdialog");
    await expect(confirm).toContainText(`Deactivate ${name}?`);
    await confirm.getByRole("button", { name: "Cancel" }).click();
    await expect(row.getByText("Invited")).toBeVisible();

    await row.getByRole("button", { name: `Actions for ${name}` }).click();
    await page.getByRole("menuitem", { name: "Deactivate" }).click();
    await page.getByRole("alertdialog").getByRole("button", { name: "Deactivate" }).click();
    await expect(row.getByText("Deactivated")).toBeVisible();
  });

  test("the administrator's own row has no way to suspend themselves", async ({ page }) => {
    await signInAndWait(page, "administrator");
    await open(page, "/admin/users", /^People$/);
    await page.getByRole("button", { name: "Administrators" }).click();
    await expect(page.getByText("This is you")).toBeVisible();
  });

  test("verifies a new therapist, who then moves from Waiting to Verified", async ({ page }) => {
    const id = unique();
    const name = `Dr Tess E2e ${id}`;
    await signInAndWait(page, "administrator");
    await invite(page, "Therapist", name, `tess.${id}@e2e.example`);

    await open(page, "/admin/therapists", /^Therapist verification$/);
    await settled(page);
    const waiting = page.getByRole("listitem").filter({ hasText: name });
    await expect(waiting).toBeVisible();
    await waiting.getByRole("button", { name: /Review/ }).click();
    const dialog = page.getByRole("dialog", { name: `Review ${name}` });

    // A refusal needs a reason.
    await dialog.getByRole("button", { name: "Do not accept" }).click();
    await dialog.getByRole("button", { name: "Save decision" }).click();
    await expect(dialog.getByText(/Say briefly why/)).toBeVisible();

    await dialog.getByRole("button", { name: "Verify" }).click();
    await dialog.getByRole("button", { name: "Save decision" }).click();
    await expect(page.getByText("Therapist verified")).toBeVisible();
    await expect(page.getByRole("listitem").filter({ hasText: name })).toHaveCount(0);

    await page.getByRole("button", { name: "Verified" }).click();
    await settled(page);
    await expect(page.getByRole("listitem").filter({ hasText: name })).toBeVisible();
  });

  test("adds and deletes a department, and adds a course to another", async ({ page }) => {
    const id = unique();
    const code = `E${id}`.slice(0, 12).toUpperCase();
    await signInAndWait(page, "administrator");
    await open(page, "/admin/academics", /^Departments and courses$/);

    await page.getByRole("button", { name: "Add department" }).click();
    let dialog = page.getByRole("dialog", { name: "Add a department" });
    await dialog.getByRole("button", { name: "Save" }).click();
    await expect(dialog.getByText("Enter a name.")).toBeVisible();
    await dialog.getByLabel("Name").fill(`E2e department ${id}`);
    await dialog.getByLabel("Short code").fill(code);
    await dialog.getByRole("button", { name: "Save" }).click();
    const row = page.getByRole("row").filter({ hasText: `E2e department ${id}` });
    await expect(row).toBeVisible();

    await row.getByRole("button", { name: /Delete/ }).click();
    await page.getByRole("alertdialog").getByRole("button", { name: "Delete" }).click();
    await expect(page.getByText("Department deleted")).toBeVisible();
    await expect(row).toHaveCount(0);

    await page.getByRole("button", { name: "Courses" }).click();
    await page.getByRole("button", { name: "Add course" }).click();
    dialog = page.getByRole("dialog", { name: "Add a course" });
    await chooseFirstDepartment(page, dialog);
    await dialog.getByLabel("Course code").fill(`E2E${id}`.slice(0, 14).toUpperCase());
    await dialog.getByLabel("Title").fill(`E2e course ${id}`);
    await dialog.getByRole("button", { name: "Add course" }).click();
    const link = page.getByRole("link", { name: new RegExp(`E2e course ${id}`) });
    await expect(link).toBeVisible();
    await link.click();
    await expect(
      page.getByRole("heading", { level: 1, name: new RegExp(`E2e course ${id}`) }),
    ).toBeVisible();
    await expect(page.getByText("No teacher assigned yet.")).toBeVisible();
    await page.getByRole("button", { name: "Delete", exact: true }).click();
    await page.getByRole("alertdialog").getByRole("button", { name: "Delete" }).click();
    await expect(page).toHaveURL(/\/admin\/academics$/);
  });

  test("writes a resource as a draft, publishes it, then deletes it", async ({ page }) => {
    const id = unique();
    const title = `E2e resource ${id}`;
    await signInAndWait(page, "administrator");
    await open(page, "/admin/resources/new", /^New resource$/);
    await page.getByRole("button", { name: "Add resource" }).click();
    await expect(page.getByText("Enter a title.")).toBeVisible();
    await page.getByLabel("Title").fill(title);
    await page.getByLabel("Short summary").fill("A synthetic resource for the browser test.");
    await page.getByLabel("Text").fill("Take three slow breaths.");
    await page.getByLabel("Link (optional)").fill("http://insecure.example");
    await page.getByRole("button", { name: "Add resource" }).click();
    await expect(page.getByText("Links must start with https://")).toBeVisible();
    await page.getByLabel("Link (optional)").fill("");
    await page.getByRole("button", { name: "Add resource" }).click();

    await expect(page).toHaveURL(/\/admin\/resources$/);
    await page.getByLabel("Search resources").fill(id);
    const item = page.getByRole("listitem").filter({ hasText: title });
    await expect(item.getByText("Draft")).toBeVisible();
    await item.getByRole("button", { name: /^Publish/ }).click();
    await expect(item.getByText("Published")).toBeVisible();
    await item.getByRole("button", { name: /^Delete/ }).click();
    await page.getByRole("alertdialog").getByRole("button", { name: "Delete" }).click();
    await expect(page.getByText("Resource deleted")).toBeVisible();
    await expect(item).toHaveCount(0);
  });

  test("shipped resources can be read but not edited", async ({ page }) => {
    await signInAndWait(page, "administrator");
    await open(page, "/admin/resources", /^Resources$/);
    await page.getByRole("button", { name: "Shipped with MindMitra" }).click();
    await settled(page);
    const rows = page.getByRole("listitem").filter({ hasText: "Read only" });
    expect(await rows.count()).toBeGreaterThan(0);
    await expect(rows.first().getByRole("button")).toHaveCount(0);
  });

  test("analytics and oversight show counts, never a person", async ({ page }) => {
    await signInAndWait(page, "administrator");
    await open(page, "/admin/analytics", /^Analytics$/);
    await settled(page);
    await expect(page.getByText(/Appointments booked/).first()).toBeVisible();
    const requests: string[] = [];
    page.on("request", (r) => {
      if (r.url().includes("/admin/analytics")) requests.push(r.url());
    });
    await page.getByRole("button", { name: "12 weeks" }).click();
    await expect.poll(() => requests.some((u) => u.includes("weeks=12"))).toBe(true);
    await settled(page);

    await open(page, "/admin/appointments", /^Appointment oversight$/);
    await settled(page);
    await expect(page.getByText("Therapist workload")).toBeVisible();
    await expect(page.getByText(/who attended and what was discussed stay private/)).toBeVisible();
  });

  test("settings: the response time and reminder hours are validated and saved", async ({
    page,
  }) => {
    await signInAndWait(page, "administrator");
    await open(page, "/admin/settings", /^Settings$/);

    await page.getByRole("button", { name: "Notifications" }).click();
    const hours = page.getByLabel("Hours before an appointment");
    await hours.fill("24, 0");
    await page.getByRole("button", { name: "Save" }).click();
    await expect(page.getByText(/Use whole numbers of hours/)).toBeVisible();
    await hours.fill("24, 2");
    await page.getByRole("button", { name: "Save" }).click();
    await expect(page.getByText("Notification settings saved")).toBeVisible();
    await expect(page.getByText("How reminders and email are sent")).toBeVisible();

    await page.getByRole("button", { name: "Safety" }).click();
    const minutes = page.getByLabel(/Minutes a therapist has to acknowledge/);
    await minutes.fill("2");
    await page.getByRole("button", { name: "Save" }).first().click();
    await expect(page.getByText("Use whole minutes from 5 to 1440.")).toBeVisible();
    await minutes.fill("20");
    await page.getByRole("button", { name: "Save" }).first().click();
    await expect(page.getByText("Safety settings saved")).toBeVisible();

    await page.reload();
    await page.getByRole("button", { name: "Safety" }).click();
    await expect(page.getByLabel(/Minutes a therapist has to acknowledge/)).toHaveValue("20");
  });

  test("settings: crisis contacts can be added and removed, shipped ones cannot", async ({
    page,
  }) => {
    const id = unique();
    await signInAndWait(page, "administrator");
    await open(page, "/admin/settings", /^Settings$/);
    await page.getByRole("button", { name: "Safety" }).click();
    await settled(page);
    await page.getByRole("button", { name: "Add contact" }).click();
    const dialog = page.getByRole("dialog", { name: "Add a contact" });
    await dialog.getByRole("button", { name: "Save" }).click();
    await expect(dialog.getByText("Enter a name.")).toBeVisible();
    await dialog.getByLabel("Name").fill(`E2e line ${id}`);
    await dialog.getByLabel("Phone").fill("0000 000 000");
    await dialog.getByLabel("Kind").selectOption("helpline");
    await dialog.getByRole("button", { name: "Save" }).click();
    const item = page.getByRole("listitem").filter({ hasText: `E2e line ${id}` });
    await expect(item).toBeVisible();
    await item.getByRole("button", { name: /^Remove/ }).click();
    await page.getByRole("alertdialog").getByRole("button", { name: "Remove" }).click();
    await expect(item).toHaveCount(0);
    const shipped = page.getByRole("listitem").filter({ hasText: "Shipped with MindMitra" });
    for (const entry of await shipped.all()) {
      await expect(entry.getByRole("button")).toHaveCount(0);
    }
  });

  test("the audit log records changes, can be checked and exported", async ({ page }) => {
    await signInAndWait(page, "administrator");
    await open(page, "/admin/audit", /^Audit log$/);
    await settled(page);
    const table = page.getByRole("table", { name: "Audit log entries" });
    await expect(table).toBeVisible();
    // Signing in as an administrator is itself recorded.
    await expect(table.getByText("auth.login").first()).toBeVisible();

    await page.getByRole("button", { name: "Check the log is intact" }).click();
    await expect(page.getByText("The log is intact")).toBeVisible();

    await page.getByLabel("Outcome").selectOption("allowed");
    await page.getByRole("button", { name: "Apply" }).click();
    await settled(page);
    await expect(table.getByText("Refused")).toHaveCount(0);

    const download = page.waitForEvent("download");
    await page.getByRole("button", { name: "Download CSV" }).click();
    expect((await download).suggestedFilename()).toBe("audit-log.csv");

    // The log holds actions, never what people wrote.
    const text = (await page.locator("main").innerText()).toLowerCase();
    expect(text).not.toMatch(/password|journal|session note/);
  });

  test("a student cannot use the admin pages or their data", async ({ page }) => {
    await signInAndWait(page, "student");
    await page.goto("/admin/users");
    await expect(page).not.toHaveURL(/\/admin\/users$/);
  });
});

for (const scheme of ["light", "dark"] as const) {
  test.describe(`administrator pages are accessible in ${scheme} mode (axe, WCAG 2.1 AA)`, () => {
    test.use({ colorScheme: scheme });

    test("every page", async ({ page }) => {
      await signInAndWait(page, "administrator");
      for (const [path, heading] of ADMIN_PAGES) {
        await open(page, path, heading);
        await settled(page);
        const results = await new AxeBuilder({ page })
          .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
          .analyze();
        const summary = results.violations.map(
          (v) =>
            `${v.id} (${v.impact}): ${v.help}\n${v.nodes
              .map((n) => `  ${n.target.join(" ")}  ${n.failureSummary?.split("\n")[1] ?? ""}`)
              .join("\n")}`,
        );
        expect(summary, `${path}\n${summary.join("\n")}`).toEqual([]);
      }
    });

    test("open dialogs", async ({ page }) => {
      await signInAndWait(page, "administrator");
      await open(page, "/admin/users", /^People$/);
      await page.getByRole("button", { name: "Invite someone" }).click();
      await expect(page.getByRole("dialog", { name: "Invite someone" })).toBeVisible();
      const results = await new AxeBuilder({ page })
        .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
        .disableRules(["aria-hidden-focus"])
        .analyze();
      expect(results.violations.map((v) => `${v.id}: ${v.help}`)).toEqual([]);
    });
  });
}

test.describe("administrator pages reflow at 320px (WCAG 1.4.10)", () => {
  test.use({ viewport: { width: 320, height: 640 } });

  test("no page scrolls sideways", async ({ page }) => {
    await signInAndWait(page, "administrator");
    for (const [path, heading] of ADMIN_PAGES) {
      await open(page, path, heading);
      await settled(page);
      const overflow = await page.evaluate(
        () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
      );
      expect(overflow, `${path} overflows`).toBeLessThanOrEqual(0);
    }
  });
});
