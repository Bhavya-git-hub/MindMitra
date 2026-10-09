import AxeBuilder from "@axe-core/playwright";
import type { Page } from "@playwright/test";

import { expect, PORTAL, ROLES, signInAndWait, test } from "./fixtures";

/**
 * `modalOpen`: while a Radix menu or dialog is open it marks the rest of the page aria-hidden
 * (so assistive technology stays inside it) and traps focus there. axe's aria-hidden-focus rule
 * does not model that, so it is skipped for those scans only.
 */
async function scan(page: Page, label: string, { modalOpen = false } = {}) {
  const results = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
    .disableRules(modalOpen ? ["aria-hidden-focus"] : [])
    .analyze();
  const summary = results.violations.map(
    (v) =>
      `${v.id} (${v.impact}): ${v.help}\n${v.nodes.map((n) => `  ${n.target.join(" ")}  ${n.failureSummary?.split("\n")[1] ?? ""}`).join("\n")}`,
  );
  expect(summary, `${label}\n${summary.join("\n")}`).toEqual([]);
}

for (const scheme of ["light", "dark"] as const) {
  test.describe(`accessibility in ${scheme} mode (axe, WCAG 2.1 AA, real browser)`, () => {
    test.use({ colorScheme: scheme });

    for (const path of ["/login", "/register", "/forgot-password", "/help", "/design-system"]) {
      test(`${path}`, async ({ page }) => {
        await page.goto(path);
        await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
        await scan(page, path);
      });
    }

    test("/login with validation errors and a server error showing", async ({ page }) => {
      await page.goto("/login");
      await page.getByRole("button", { name: "Sign in" }).click();
      await expect(page.getByText("Enter your email address")).toBeVisible();
      await scan(page, "login validation");
    });

    for (const role of ROLES) {
      test(`${role} portal home and account`, async ({ page }) => {
        await signInAndWait(page, role);
        await scan(page, `${role} home`);
        await page.goto(`${PORTAL[role]}/account`);
        await expect(page.getByRole("heading", { level: 1, name: "Account" })).toBeVisible();
        await scan(page, `${role} account`);
      });
    }

    test("open dialogs and menus", async ({ page }) => {
      await signInAndWait(page, "student");
      await page.getByRole("button", { name: "Account menu" }).click();
      await expect(page.getByRole("menu")).toBeVisible();
      await scan(page, "user menu", { modalOpen: true });
      await page.keyboard.press("Escape");
      await page.getByRole("button", { name: "Change colour theme" }).click();
      await expect(page.getByRole("menu")).toBeVisible();
      await scan(page, "theme menu", { modalOpen: true });
      await page.keyboard.press("Escape");
      await page.goto("/student/account");
      await page.getByRole("button", { name: "Sign out" }).click();
      await expect(page.getByRole("alertdialog")).toBeVisible();
      await scan(page, "sign out dialog", { modalOpen: true });
    });
  });
}

test.describe("theme", () => {
  test("follows the device setting and can be changed", async ({ page }) => {
    await signInAndWait(page, "student");
    const html = page.locator("html");
    await page.getByRole("button", { name: "Change colour theme" }).click();
    await page.getByRole("menuitem", { name: "Dark" }).click();
    await expect(html).toHaveClass(/dark/);
    await page.reload();
    await expect(html).toHaveClass(/dark/);
    await page.getByRole("button", { name: "Change colour theme" }).click();
    await page.getByRole("menuitem", { name: "Light" }).click();
    await expect(html).not.toHaveClass(/dark/);
  });
});
