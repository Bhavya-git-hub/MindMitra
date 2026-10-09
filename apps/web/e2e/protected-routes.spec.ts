import { expect, PORTAL, ROLES, signIn, signInAndWait, test, type Role } from "./fixtures";

test.describe("protected routes (signed out)", () => {
  for (const role of ROLES) {
    test(`${PORTAL[role]} sends a visitor to /login and remembers the page`, async ({ page }) => {
      await page.goto(`${PORTAL[role]}/account`);
      await expect(page).toHaveURL(
        new RegExp(
          `/login\\?next=${encodeURIComponent(`${PORTAL[role]}/account`).replace(/%/g, "%")}$`,
        ),
      );
      await expect(page.getByRole("heading", { level: 1, name: "Welcome back" })).toBeVisible();
    });
  }

  test("the root sends visitors to /login", async ({ page }) => {
    await page.goto("/");
    await expect(page).toHaveURL(/\/login$/);
  });

  test("public pages stay open", async ({ page }) => {
    for (const [path, heading] of [
      ["/login", "Welcome back"],
      ["/register", "Create your account"],
      ["/forgot-password", "Reset your password"],
      ["/help", /You don't have to handle this alone/],
    ] as const) {
      await page.goto(path);
      await expect(page.getByRole("heading", { level: 1 })).toContainText(heading);
    }
  });

  test("unknown pages show a calm 404", async ({ page }) => {
    const response = await page.goto("/no-such-page");
    expect(response?.status()).toBe(404);
    await expect(page.getByRole("heading", { name: "We can't find that page" })).toBeVisible();
  });

  test("a forged pass cookie does not open a portal", async ({ page, context }) => {
    await context.addCookies([
      {
        name: "__Host-mm_portal",
        value: "eyJyIjoiYWRtaW5pc3RyYXRvciJ9.AAAA",
        domain: "localhost",
        path: "/",
        secure: true,
        httpOnly: true,
      },
    ]);
    await page.goto("/admin");
    await expect(page).toHaveURL(/\/login\?next=%2Fadmin$/);
  });
});

test.describe("a stale but validly signed pass", () => {
  test("is not enough: the page checks the real session, clears the pass, and does not loop", async ({
    page,
    context,
  }) => {
    // Sign a pass the way the server would. (The secret is shared with the web server by the runner.)
    const secret = process.env.SESSION_SECRET ?? "";
    test.skip(secret.length < 32, "SESSION_SECRET not exposed to the test process");
    const { signPass } = await import("../src/lib/auth/pass");
    await context.addCookies([
      {
        name: "__Host-mm_portal",
        value: await signPass("administrator", secret),
        domain: "localhost",
        path: "/",
        secure: true,
        httpOnly: true,
      },
    ]);

    await page.goto("/admin");
    // The proxy lets it through; the client finds no session and sends the person to sign in.
    await expect(page).toHaveURL(/\/login/, { timeout: 15_000 });
    await expect(page.getByRole("heading", { level: 1, name: "Welcome back" })).toBeVisible();
    // The stale pass was cleared, so /login is stable (it does not bounce back to /admin).
    await page.waitForTimeout(500);
    await expect(page).toHaveURL(/\/login/);
    expect(
      (await context.cookies()).some((c) => c.name === "__Host-mm_portal" && c.value !== ""),
    ).toBe(false);
  });
});

test.describe("role-based redirects (signed in)", () => {
  for (const role of ROLES) {
    for (const other of ROLES.filter((r) => r !== role)) {
      test(`a ${role} opening the ${other} portal is sent home`, async ({ page }) => {
        await signInAndWait(page, role);
        await page.goto(`${PORTAL[other]}/account`);
        await expect(page).toHaveURL(new RegExp(`${PORTAL[role]}$`));
        await expect(page.getByRole("heading", { level: 1 })).toContainText("Welcome");
        // None of the other portal's content was rendered.
        await expect(
          page.getByRole("navigation", { name: new RegExp(`^${labelFor(other)}`) }),
        ).toHaveCount(0);
      });
    }

    test(`a ${role} visiting /login or / is sent to their portal`, async ({ page }) => {
      await signInAndWait(page, role);
      await page.goto("/login");
      await expect(page).toHaveURL(new RegExp(`${PORTAL[role]}$`));
      await page.goto("/");
      await expect(page).toHaveURL(new RegExp(`${PORTAL[role]}$`));
    });
  }

  test("returns to the page that was asked for after signing in", async ({ page }) => {
    await page.goto("/student/account");
    await expect(page).toHaveURL(/\/login\?next=/);
    const { credentials } = await import("./fixtures");
    await page.getByLabel("Email").fill(credentials("student").email);
    await page.getByLabel("Password", { exact: true }).fill(credentials("student").password);
    await page.getByRole("button", { name: "Sign in" }).click();
    await expect(page).toHaveURL(/\/student\/account$/);
    await expect(page.getByRole("heading", { level: 1, name: "Account" })).toBeVisible();
  });

  for (const next of [
    "/admin",
    "//evil.example",
    "https://evil.example/student",
    "/therapist/notes",
  ]) {
    test(`ignores an unsafe or foreign next=${next}`, async ({ page }) => {
      await signIn(page, "student", next);
      await expect(page).toHaveURL(/\/student$/);
    });
  }

  test("the API, not the page, is what protects data: a student's token is refused on admin endpoints", async ({
    page,
  }) => {
    await signInAndWait(page, "student");
    const status = await page.evaluate(async (base) => {
      // Borrow the in-memory token the app itself would use, by signing in again via fetch.
      const csrf = localStorage.getItem("mm.csrf") ?? "";
      const refreshed = await fetch(`${base}/api/v1/auth/refresh`, {
        method: "POST",
        credentials: "include",
        headers: { "X-CSRF-Token": csrf },
      });
      const { access_token } = (await refreshed.json()) as { access_token: string };
      const res = await fetch(`${base}/api/v1/admin/users`, {
        headers: { Authorization: `Bearer ${access_token}` },
      });
      return res.status;
    }, process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000");
    expect([403, 404]).toContain(status);
  });
});

function labelFor(role: Role): string {
  return role === "administrator" ? "Administrator" : role[0]!.toUpperCase() + role.slice(1);
}
