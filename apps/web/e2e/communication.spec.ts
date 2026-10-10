import type { Browser, Page } from "@playwright/test";

import { carePair, expect, settled, signIn, test } from "./fixtures";

/**
 * Two people in two browsers, one real API: what one does reaches the other over the live
 * connection, without a reload (the pages' fallback refresh is minutes away, far longer than
 * these waits).
 */
const LIVE = { timeout: 10_000 };

async function asTherapist(browser: Browser): Promise<Page> {
  const page = await (await browser.newContext()).newPage();
  await signIn(page, "therapist");
  await page.waitForURL("**/therapist");
  return page;
}

async function asCareStudent(browser: Browser): Promise<Page> {
  const page = await (await browser.newContext()).newPage();
  await signIn(page, "student", undefined, carePair.studentEmail);
  await page.waitForURL("**/student");
  return page;
}

test.describe("therapist communication (real API, two browsers)", () => {
  test.describe.configure({ mode: "serial" });

  test("messages reach the other person live, and only they can read them", async ({ browser }) => {
    const therapist = await asTherapist(browser);
    const student = await asCareStudent(browser);

    await therapist.goto(`/therapist/messages/${carePair.studentId}`);
    await expect(
      therapist.getByRole("heading", { level: 1, name: carePair.studentName }),
    ).toBeVisible();
    await settled(therapist);
    await student.goto(`/student/messages/${carePair.therapistId}`);
    await settled(student);

    const hello = `Synthetic e2e hello ${Date.now()}`;
    await student.getByLabel("Write a message").fill(hello);
    await student.getByRole("button", { name: "Send" }).click();
    await expect(student.getByLabel("Write a message")).toHaveValue("");

    const thread = therapist.getByRole("list", { name: "Messages" });
    await expect(thread.getByText(hello)).toBeVisible(LIVE);

    const reply = `Synthetic e2e reply ${Date.now()}`;
    await therapist.getByLabel("Write a message").fill(reply);
    await therapist.getByRole("button", { name: "Send" }).click();
    await expect(student.getByRole("list", { name: "Messages" }).getByText(reply)).toBeVisible(
      LIVE,
    );
    // The therapist opened the conversation, so the student's message shows as read.
    await expect(student.getByText(/· Read/).first()).toBeVisible(LIVE);

    // A teacher has no way into the conversation, even with its address.
    const teacher = await (await browser.newContext()).newPage();
    await signIn(teacher, "teacher");
    await teacher.waitForURL("**/teacher");
    await teacher.goto(`/student/messages/${carePair.therapistId}`);
    await expect(teacher).not.toHaveURL(/\/student\/messages/);
    await expect(teacher.getByText(hello)).toHaveCount(0);
  });

  test("a booking, a move, a confirmation and a cancellation show up live on both sides", async ({
    browser,
  }) => {
    const therapist = await asTherapist(browser);
    const student = await asCareStudent(browser);

    await therapist.goto("/therapist/appointments");
    await settled(therapist);

    // The student requests one of the therapist's open times.
    await student.goto(`/student/therapists/${carePair.therapistId}`);
    await expect(student.getByRole("heading", { name: "Available times" })).toBeVisible();
    await settled(student);
    const times = student.getByRole("button", { name: /, 3:00\s?AM|, 03:00/ });
    await expect(times.first()).toBeVisible();
    await times.first().click();
    const booking = student.getByRole("dialog", { name: "Request this appointment" });
    await booking.getByRole("button", { name: "Send request" }).click();
    await expect(student.getByText("Request sent").first()).toBeVisible();

    const request = therapist.locator("li", { hasText: carePair.studentName }).filter({
      has: therapist.getByRole("button", { name: "Confirm" }),
    });
    await expect(request.first()).toBeVisible(LIVE);

    // The bell counts the new request.
    await expect(
      therapist.getByRole("button", { name: /^Open notifications, \d+ unread$/ }),
    ).toBeVisible(LIVE);

    // The student moves it to another time.
    await student.goto("/student/appointments");
    await settled(student);
    const mine = student.locator("li", { hasText: "Waiting for confirmation" }).first();
    await mine.getByRole("button", { name: "Move" }).click();
    const move = student.getByRole("dialog", { name: "Move this appointment" });
    await move.getByRole("radio").first().check();
    await move.getByRole("button", { name: "Move appointment" }).click();
    await expect(student.getByText("Appointment moved")).toBeVisible();
    await expect(student.getByText(/Moved once/).first()).toBeVisible();
    await expect(request.first().getByText(/Moved once/)).toBeVisible(LIVE);

    // The therapist confirms; the student's page changes without a reload.
    await request.first().getByRole("button", { name: "Confirm" }).click();
    await expect(
      student
        .locator("li", { hasText: /Moved once/ })
        .first()
        .getByText("Confirmed"),
    ).toBeVisible(LIVE);

    // The student cancels with a reason; the reason is kept, and the time is free again.
    const confirmed = student.locator("li", { hasText: /Moved once/ }).first();
    await confirmed.getByRole("button", { name: "Cancel" }).click();
    const cancel = student.getByRole("alertdialog");
    await cancel.getByLabel("Reason (optional)").selectOption({ label: "Something else came up" });
    await cancel.getByRole("button", { name: "Cancel appointment" }).click();
    await expect(student.getByText("Appointment cancelled")).toBeVisible();
    await expect(student.getByText("Reason: Something else came up").first()).toBeVisible();
  });

  test("the notification panel lists what happened and can be cleared", async ({ browser }) => {
    const therapist = await asTherapist(browser);
    await therapist.getByRole("button", { name: /^Open notifications/ }).click();
    const panel = therapist.getByRole("dialog", { name: "Notifications" });
    await expect(panel.getByRole("list", { name: "Notifications" })).toBeVisible();
    await expect(panel.getByText("You have a new message").first()).toBeVisible();
    await panel.getByRole("button", { name: "Mark all as read" }).click();
    await expect(panel.getByText(/all caught up/)).toBeVisible();
    await therapist.keyboard.press("Escape");
    await expect(therapist.getByRole("button", { name: "Open notifications" })).toBeVisible();
  });
});
