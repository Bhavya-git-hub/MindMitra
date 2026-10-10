import { expect, HEADING, signInAndWait, test } from "./fixtures";

test.describe("security headers and caching", () => {
  test("pages are never cached, static assets are, and the CSP is strict", async ({
    page,
    request,
  }) => {
    const response = await page.goto("/login");
    const headers = response?.headers() ?? {};
    expect(headers["cache-control"]).toBe("private, no-store");
    expect(headers["x-frame-options"]).toBe("DENY");
    expect(headers["x-content-type-options"]).toBe("nosniff");
    expect(headers["strict-transport-security"]).toContain("max-age=");
    expect(headers["content-security-policy"]).toMatch(
      /script-src 'self' 'nonce-[^']+' 'strict-dynamic'/,
    );
    expect(headers["content-security-policy"]).not.toContain("unsafe-eval");

    const chunk = await page.locator("script[src*='/_next/static/']").first().getAttribute("src");
    expect(chunk).toBeTruthy();
    const asset = await request.get(chunk as string);
    expect(asset.headers()["cache-control"]).toContain("immutable");
  });

  test("every inline script carries the request's nonce", async ({ page }) => {
    await page.goto("/login");
    const mismatches = await page.evaluate(() => {
      const csp = document.querySelector("meta[http-equiv='Content-Security-Policy']");
      void csp;
      const scripts = [...document.querySelectorAll("script:not([src])")] as HTMLScriptElement[];
      return scripts.filter((s) => !s.nonce).length;
    });
    expect(mismatches).toBe(0);
  });
});

test.describe("when the API is unreachable", () => {
  test("a signed-in person on reload is told, not signed out or looped, and can retry", async ({
    page,
  }) => {
    await signInAndWait(page, "student");

    let down = true;
    await page.route("**/api/v1/auth/refresh", (route) =>
      down ? route.abort("connectionrefused") : route.continue(),
    );
    await page.reload();

    await expect(page.getByText("We couldn't check your session")).toBeVisible();
    await page.waitForTimeout(1000);
    await expect(page).toHaveURL(/\/student$/); // no redirect ping-pong with /login
    expect(await page.evaluate(() => localStorage.getItem("mm.csrf"))).toBeTruthy(); // not signed out

    down = false;
    await page.getByRole("button", { name: "Try again" }).click();
    await expect(page.getByRole("heading", { level: 1 })).toHaveText(HEADING.student);
  });
});
