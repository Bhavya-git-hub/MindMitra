import { credentials, expect, PORTAL, ROLES, signIn, signInAndWait, test } from "./fixtures";

test.describe("login", () => {
  for (const role of ROLES) {
    test(`a ${role} signs in and lands in their own portal`, async ({ page }) => {
      await signInAndWait(page, role);
      await expect(page).toHaveURL(new RegExp(`${PORTAL[role]}$`));
      await expect(page.getByRole("navigation", { name: /navigation$/ })).toBeVisible();
    });
  }

  test("wrong password shows one generic message and keeps the person on /login", async ({
    page,
  }) => {
    const { email } = credentials("student");
    await page.goto("/login");
    await page.getByLabel("Email").fill(email);
    await page.getByLabel("Password", { exact: true }).fill("definitely-not-the-password");
    await page.getByRole("button", { name: "Sign in" }).click();
    await expect(page.getByRole("alert").filter({ hasText: /./ })).toContainText(
      "That email and password don't match",
    );
    await expect(page).toHaveURL(/\/login$/);
    await expect(page.getByLabel("Password", { exact: true })).toHaveValue("");
  });

  test("an unknown email gets exactly the same message", async ({ page }) => {
    await page.goto("/login");
    await page.getByLabel("Email").fill("nobody@students.synthetic.example");
    await page.getByLabel("Password", { exact: true }).fill("definitely-not-the-password");
    await page.getByRole("button", { name: "Sign in" }).click();
    await expect(page.getByRole("alert").filter({ hasText: /./ })).toContainText(
      "That email and password don't match",
    );
  });

  test("validates empty fields in the browser before calling the API", async ({ page }) => {
    await page.goto("/login");
    await page.getByRole("button", { name: "Sign in" }).click();
    await expect(page.getByText("Enter your email address")).toBeVisible();
    await expect(page.getByText("Enter your password")).toBeVisible();
  });

  test("shows a friendly message when rate limited", async ({ page }) => {
    await page.route("**/api/v1/auth/login", (route) =>
      route.fulfill({
        status: 429,
        contentType: "application/problem+json",
        headers: {
          "Retry-After": "42",
          "Access-Control-Allow-Origin": "http://localhost:3000",
          "Access-Control-Allow-Credentials": "true",
          "Access-Control-Expose-Headers": "Retry-After",
        },
        body: JSON.stringify({
          title: "Too many requests",
          status: 429,
          detail: "Too many requests",
        }),
      }),
    );
    await signIn(page, "student");
    await expect(page.getByRole("alert").filter({ hasText: /./ })).toContainText(
      "wait about 42 seconds",
    );
  });

  test("shows a friendly message when the API is unreachable", async ({ page }) => {
    await page.route("**/api/v1/auth/login", (route) => route.abort("connectionrefused"));
    await signIn(page, "student");
    await expect(page.getByRole("alert").filter({ hasText: /./ })).toContainText(
      "couldn't reach MindMitra",
    );
  });
});

test.describe("session storage and cookies", () => {
  test("no token is readable by page scripts; only the CSRF token is stored", async ({
    page,
    context,
  }) => {
    await signInAndWait(page, "student");

    const storage = await page.evaluate(() => ({
      local: Object.fromEntries(Object.entries(localStorage)),
      session: Object.fromEntries(Object.entries(sessionStorage)),
      cookie: document.cookie,
    }));
    expect(Object.keys(storage.local)).toEqual(["mm.csrf"]);
    expect(storage.session).toEqual({});
    expect(storage.cookie).toBe("");
    expect(JSON.stringify(storage)).not.toMatch(/eyJ/); // no JWT anywhere

    const cookies = await context.cookies();
    const refresh = cookies.find((c) => c.name === "__Secure-mm_refresh");
    expect(refresh).toMatchObject({ httpOnly: true, secure: true, sameSite: "Strict" });
    expect(refresh?.path).toBe("/api/v1/auth");
    const pass = cookies.find((c) => /mm_portal$/.test(c.name));
    expect(pass).toMatchObject({ httpOnly: true });
    expect(pass?.value).not.toContain("student"); // an opaque signed value, not a readable role
  });

  test("a reload keeps the person signed in (refresh-token rotation)", async ({
    page,
    context,
  }) => {
    await signInAndWait(page, "teacher");
    const before = await page.evaluate(() => localStorage.getItem("mm.csrf"));
    await page.reload();
    await expect(page.getByRole("heading", { level: 1 })).toContainText("Welcome");
    await expect(page).toHaveURL(/\/teacher$/);
    const after = await page.evaluate(() => localStorage.getItem("mm.csrf"));
    expect(after).toBeTruthy();
    expect(after).not.toBe(before); // rotated on refresh
    expect((await context.cookies()).some((c) => c.name === "__Secure-mm_refresh")).toBe(true);
  });

  test("a new tab in the same browser restores the session", async ({ page, context }) => {
    await signInAndWait(page, "therapist");
    const second = await context.newPage();
    await second.goto("/therapist/account");
    await expect(second.getByRole("heading", { level: 1, name: "Account" })).toBeVisible();
    await second.close();
  });
});

test.describe("logout", () => {
  test("asks for confirmation, then ends the session everywhere", async ({ page, context }) => {
    await signInAndWait(page, "student");
    await page.goto("/student/account");
    await page.getByRole("button", { name: "Sign out" }).click();
    const dialog = page.getByRole("alertdialog");
    await expect(dialog).toBeVisible();
    await dialog.getByRole("button", { name: "Sign out" }).click();

    await expect(page).toHaveURL(/\/login$/);
    await expect(page.getByText("You're signed out")).toBeVisible();

    // The refresh cookie is gone and the stored CSRF token cleared.
    expect((await context.cookies()).some((c) => c.name === "__Secure-mm_refresh")).toBe(false);
    expect(await page.evaluate(() => localStorage.getItem("mm.csrf"))).toBeNull();

    // Protected pages are closed again, and Back does not reopen the portal.
    await page.goto("/student");
    await expect(page).toHaveURL(/\/login\?next=%2Fstudent$/);
    await page.goBack();
    await page.goto("/student/account");
    await expect(page).toHaveURL(/\/login\?next=/);
  });

  test("cancelling keeps the session", async ({ page }) => {
    await signInAndWait(page, "student");
    await page.goto("/student/account");
    await page.getByRole("button", { name: "Sign out" }).click();
    await page.getByRole("alertdialog").getByRole("button", { name: "Cancel" }).click();
    await expect(page).toHaveURL(/\/student\/account$/);
    await expect(page.getByRole("button", { name: "Sign out" })).toBeFocused();
  });

  test("signing out from the header menu works", async ({ page }) => {
    await signInAndWait(page, "administrator");
    await page.getByRole("button", { name: "Account menu" }).click();
    await page.getByRole("menuitem", { name: "Sign out" }).click();
    await expect(page).toHaveURL(/\/login$/);
  });

  test("the old refresh token cannot be replayed after sign-out", async ({
    page,
    context,
    request,
  }) => {
    await signInAndWait(page, "student");
    const cookie = (await context.cookies()).find((c) => c.name === "__Secure-mm_refresh");
    const csrf = await page.evaluate(() => localStorage.getItem("mm.csrf"));
    expect(cookie && csrf).toBeTruthy();

    await page.goto("/student/account");
    await page.getByRole("button", { name: "Sign out" }).click();
    await page.getByRole("alertdialog").getByRole("button", { name: "Sign out" }).click();
    await expect(page).toHaveURL(/\/login$/);

    const apiBase = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";
    const replay = await request.post(`${apiBase}/api/v1/auth/refresh`, {
      headers: { "X-CSRF-Token": csrf as string, Cookie: `__Secure-mm_refresh=${cookie?.value}` },
    });
    expect(replay.status()).toBe(401);
  });

  test("signing out in one tab signs out the other", async ({ page, context }) => {
    await signInAndWait(page, "teacher");
    const other = await context.newPage();
    await other.goto("/teacher/account");
    await expect(other.getByRole("heading", { level: 1, name: "Account" })).toBeVisible();

    await page.goto("/teacher/account");
    await page.getByRole("button", { name: "Sign out" }).click();
    await page.getByRole("alertdialog").getByRole("button", { name: "Sign out" }).click();
    await expect(page).toHaveURL(/\/login$/);

    await expect(other).toHaveURL(/\/login/, { timeout: 10_000 });
  });
});
