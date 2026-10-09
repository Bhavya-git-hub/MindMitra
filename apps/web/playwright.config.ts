import { defineConfig, devices } from "@playwright/test";

const port = Number(process.env.E2E_WEB_PORT ?? 3000);

/**
 * End-to-end tests run against a real API and database (see scripts/e2e/run.sh) and a
 * production build of this app, so cookies, the CSP nonce and the proxy behave as deployed.
 */
export default defineConfig({
  testDir: "./e2e",
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  workers: process.env.CI ? 2 : undefined,
  reporter: process.env.CI ? [["github"], ["html", { open: "never" }]] : "list",
  use: {
    baseURL: `http://localhost:${port}`,
    trace: "retain-on-failure",
  },
  projects: [
    {
      name: "chromium",
      use: {
        ...devices["Desktop Chrome"],
        // Use a pre-installed browser when one is provided; otherwise Playwright's own.
        launchOptions: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH
          ? { executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH }
          : {},
      },
    },
  ],
  webServer: {
    command: `npm run start -- --port ${port}`,
    url: `http://localhost:${port}/login`,
    reuseExistingServer: false,
    timeout: 60_000,
    env: {
      SESSION_SECRET: process.env.SESSION_SECRET ?? "",
      NEXT_PUBLIC_API_BASE_URL: process.env.NEXT_PUBLIC_API_BASE_URL ?? "",
      ENABLE_DESIGN_SYSTEM: "true",
    },
  },
});
