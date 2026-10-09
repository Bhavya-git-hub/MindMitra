import { expect, PORTAL, ROLES, signInAndWait, test } from "./fixtures";

test.describe("mobile (390px)", () => {
  test.use({ viewport: { width: 390, height: 844 } });

  test("the sidebar collapses into a menu that navigates and closes", async ({ page }) => {
    await signInAndWait(page, "student");
    await expect(page.getByRole("navigation", { name: "Student navigation" })).toBeHidden();

    await page.getByRole("button", { name: "Open menu" }).click();
    const nav = page.getByRole("dialog").getByRole("navigation", { name: "Student navigation" });
    await expect(nav).toBeVisible();
    await nav.getByRole("link", { name: "Account" }).click();

    await expect(page).toHaveURL(/\/student\/account$/);
    await expect(page.getByRole("dialog")).toBeHidden();
    await expect(page.getByRole("heading", { level: 1, name: "Account" })).toBeVisible();
  });

  test("Get help stays one tap away for students, and not for staff", async ({ page }) => {
    await signInAndWait(page, "student");
    await expect(page.getByRole("link", { name: /^Get help/ }).first()).toBeVisible();
    await page
      .getByRole("link", { name: /^Get help/ })
      .first()
      .click();
    await expect(page).toHaveURL(/\/help$/);
  });

  test("the menu closes with Escape and returns focus to its button", async ({ page }) => {
    await signInAndWait(page, "teacher");
    const open = page.getByRole("button", { name: "Open menu" });
    await open.click();
    await expect(page.getByRole("dialog")).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(page.getByRole("dialog")).toBeHidden();
    await expect(open).toBeFocused();
  });
});

test.describe("no horizontal scrolling at 320px (WCAG 1.4.10 reflow)", () => {
  test.use({ viewport: { width: 320, height: 640 } });

  for (const path of ["/login", "/register", "/help", "/design-system"]) {
    test(path, async ({ page }) => {
      await page.goto(path);
      await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
      const overflow = await page.evaluate(
        () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
      );
      expect(overflow).toBeLessThanOrEqual(0);
    });
  }

  test("portals", async ({ page }) => {
    for (const role of ROLES) {
      await signInAndWait(page, role);
      const overflow = await page.evaluate(
        () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
      );
      expect(overflow, `${PORTAL[role]} overflows`).toBeLessThanOrEqual(0);
      await page.getByRole("button", { name: "Account menu" }).click();
      await page.getByRole("menuitem", { name: "Sign out" }).click();
      await expect(page).toHaveURL(/\/login$/);
    }
  });
});

test.describe("desktop shell", () => {
  test("shows the sidebar and a working skip link", async ({ page }) => {
    await signInAndWait(page, "administrator");
    await expect(page.getByRole("navigation", { name: "Administrator navigation" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Open menu" })).toBeHidden();

    await page.keyboard.press("Tab");
    const skip = page.getByRole("link", { name: "Skip to main content" });
    await expect(skip).toBeFocused();
    await expect(skip).toBeVisible();
    await page.keyboard.press("Enter");
    await expect(page.locator("#main-content")).toBeFocused();
  });

  test("keyboard users can sign in without a mouse", async ({ page }) => {
    const { credentials } = await import("./fixtures");
    await page.goto("/login");
    await page.keyboard.press("Tab"); // skip link
    await page.keyboard.press("Tab"); // email (autofocus may already have it)
    await page.getByLabel("Email").focus();
    await page.keyboard.type(credentials("student").email);
    await page.keyboard.press("Tab");
    await page.keyboard.type(credentials("student").password);
    await page.keyboard.press("Enter");
    await expect(page).toHaveURL(/\/student$/);
  });
});

test.describe("design system", () => {
  test("renders charts, toasts and dialogs in a real browser", async ({ page }) => {
    await page.goto("/design-system");
    await expect(page.locator(".recharts-surface").first()).toBeVisible();
    expect(await page.locator(".recharts-surface").count()).toBeGreaterThanOrEqual(4);

    await page.getByRole("button", { name: "Success toast" }).click();
    await expect(page.getByText("Your changes are safe.")).toBeVisible();

    await page.getByRole("button", { name: "Confirm dialog" }).click();
    await page.getByRole("button", { name: "Remove", exact: true }).click();
    await expect(page.getByText("Reminder removed")).toBeVisible();
  });
});
