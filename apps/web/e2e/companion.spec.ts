import AxeBuilder from "@axe-core/playwright";
import type { Browser, Page } from "@playwright/test";

import { carePair, expect, settled, signIn, signInAndWait, test } from "./fixtures";

/**
 * The AI companion end to end: browser, API, the internal AI service (with its offline fake
 * model) and the safety layer. All text here is synthetic.
 */
const REPLY = { timeout: 15_000 };

async function asCareStudent(browser: Browser): Promise<Page> {
  const page = await (await browser.newContext()).newPage();
  await signIn(page, "student", undefined, carePair.studentEmail);
  await page.waitForURL("**/student");
  return page;
}

async function startConversation(page: Page) {
  await page.goto("/student/assistant");
  await expect(page.getByRole("heading", { level: 1, name: "Companion" })).toBeVisible();
  await expect(page.getByText(/not a therapist/).first()).toBeVisible();
  await page.getByRole("button", { name: "Start a conversation" }).click();
  await page.waitForURL(/\/student\/assistant\/[0-9a-f-]{36}$/);
  await settled(page);
}

test.describe("AI companion (real API and AI service)", () => {
  test("a student talks about exam stress, gets a supportive reply, then deletes it", async ({
    page,
  }) => {
    await signInAndWait(page, "student");
    await startConversation(page);
    await expect(page.getByRole("note")).toContainText("can't diagnose");

    await page.getByLabel("Your message").fill("I'm really stressed about my exams next week");
    await page.getByRole("button", { name: "Send" }).click();
    const log = page.getByRole("log", { name: "Messages" });
    await expect(log.getByText(/one small next step/)).toBeVisible(REPLY);
    await expect(page.getByLabel("Your message")).toHaveValue("");
    // An everyday worry gets no crisis panel.
    await expect(page.getByRole("alert", { name: "Please talk to a person now" })).toHaveCount(0);

    const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa"]).analyze();
    expect(results.violations).toEqual([]);

    await page.getByRole("button", { name: "Delete" }).click();
    await page.getByRole("alertdialog").getByRole("button", { name: "Delete" }).click();
    await page.waitForURL("**/student/assistant");
  });

  test("a crisis message shows contacts at once and reaches the student's therapist", async ({
    browser,
  }) => {
    const student = await asCareStudent(browser);
    await startConversation(student);

    await student.getByLabel("Your message").fill("I don't want to live anymore");
    await student.getByRole("button", { name: "Send" }).click();
    const panel = student.getByRole("alert", { name: "Please talk to a person now" });
    await expect(panel).toBeVisible(REPLY);
    await expect(panel.getByRole("link", { name: /^Call / }).first()).toBeVisible();
    await expect(panel.getByRole("link", { name: "Get help now" })).toHaveAttribute(
      "href",
      "/student/emergency",
    );
    await expect(student.getByRole("log", { name: "Messages" })).toContainText(
      "I've let your counsellor know",
    );

    // The therapist sees who needs support and where it came from, never what was written.
    const therapist = await (await browser.newContext()).newPage();
    await signIn(therapist, "therapist");
    await therapist.waitForURL("**/therapist");
    await therapist.goto("/therapist/alerts");
    await settled(therapist);
    const card = therapist
      .getByRole("listitem")
      .filter({ hasText: carePair.studentName })
      .filter({ hasText: "From the AI companion" });
    await expect(card.first()).toBeVisible();
    await expect(therapist.getByText("I don't want to live anymore")).toHaveCount(0);
  });
});
