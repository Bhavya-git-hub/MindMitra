import { crisisStudentEmail, expect, open, settled, signIn, test } from "./fixtures";

/**
 * Runs against its own student (see scripts/e2e/prepare_backend.py): a crisis check-in pauses
 * that student's suggestions for 72 hours, which would break the shared student's tests.
 * The note is synthetic test text that the crisis rules must catch.
 */
test.describe("safety (real API)", () => {
  test("a concerning check-in puts help first and pauses suggestions", async ({ page }) => {
    await signIn(page, "student", undefined, crisisStudentEmail);
    await page.waitForURL("**/student");
    await expect(page.getByRole("heading", { level: 1, name: /^Hello, / })).toBeVisible();

    await open(page, "/student/check-in", /^Daily check-in$/);
    await page
      .getByRole("group", { name: "Mood", exact: true })
      .getByLabel("Very low")
      .check({ force: true });
    await page
      .getByLabel("Private note")
      .fill("I've been saving pills and I'm going to take them all tonight");
    await page.getByRole("button", { name: /Save check-in/ }).click();

    const panel = page.getByRole("alert", { name: "Please talk to a person now" });
    await expect(panel).toBeVisible();
    await expect(panel.getByText("If you're in danger right now")).toBeVisible();
    await expect(panel.getByRole("link", { name: /^Call / }).first()).toBeVisible();
    await expect(panel.getByRole("link", { name: "Get help now" })).toBeVisible();

    await open(page, "/student/recommendations", /^Suggestions$/);
    await settled(page);
    await expect(page.getByText("Suggestions are paused for now")).toBeVisible();
  });
});
