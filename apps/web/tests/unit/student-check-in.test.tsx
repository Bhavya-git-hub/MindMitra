import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { CheckInView } from "@/components/student/check-in-view";
import { MoodView, SleepView, StressView } from "@/components/student/trackers";
import type { CheckInResult } from "@/lib/api/student-schemas";

import { expectNoA11yViolations } from "../helpers/a11y";
import { json, problem, renderWithApp } from "../helpers/render";
import { studentSession, trendPoint } from "../helpers/student-data";

const moodEntry = {
  id: "e1",
  mood_score: 4,
  energy_level: null,
  emotions: ["calm"],
  note: null,
  logged_at: "2026-10-10T08:00:00Z",
};

const result = (support: CheckInResult["support"] = null): CheckInResult => ({
  mood: moodEntry,
  stress: null,
  sleep: null,
  support,
});

const pick = (group: string, label: RegExp | string) =>
  within(screen.getByRole("group", { name: group })).getByRole("radio", { name: label });

describe("daily check-in", () => {
  it("needs a mood and says so, without calling the API", async () => {
    const session = studentSession({ "POST /me/check-ins": () => json(result(), 201) });
    renderWithApp(<CheckInView />, session);
    await screen.findByRole("heading", { level: 1, name: "Daily check-in" });
    await userEvent.setup().click(screen.getByRole("button", { name: "Save check-in" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/feeling/i);
    expect(session.api.calls.some((c) => c.method === "POST" && c.path === "/me/check-ins")).toBe(
      false,
    );
  });

  it("sends mood, feelings, stress and note together, with the student's time zone", async () => {
    const session = studentSession({ "POST /me/check-ins": () => json(result(), 201) });
    renderWithApp(<CheckInView />, session);
    const user = userEvent.setup();
    await screen.findByRole("heading", { level: 1 });

    await user.click(pick("Mood", /Good/));
    await user.click(screen.getByRole("button", { name: "calm" }));
    await user.click(pick("How stressed do you feel?", /Some stress/));
    await user.click(screen.getByRole("button", { name: "exams" }));
    await user.type(screen.getByLabelText("Private note"), "Long day but fine");
    await user.click(screen.getByRole("button", { name: "Save check-in" }));

    expect(
      await screen.findByRole("heading", { level: 1, name: "Thanks for checking in" }),
    ).toBeInTheDocument();
    const post = session.api.calls.find((c) => c.method === "POST" && c.path === "/me/check-ins")!;
    expect(post.body).toEqual({
      mood_score: 4,
      emotions: ["calm"],
      stress_level: 3,
      stressors: ["exams"],
      note: "Long day but fine",
    });
    expect(post.query.get("tz")).toBeTruthy();
  });

  it("adds sleep as two exact times only when the student opts in", async () => {
    const session = studentSession({ "POST /me/check-ins": () => json(result(), 201) });
    renderWithApp(<CheckInView />, session);
    const user = userEvent.setup();
    await screen.findByRole("heading", { level: 1 });
    await user.click(pick("Mood", /Okay/));
    await user.click(screen.getByLabelText(/Add last night's sleep/));
    expect(screen.getByText(/about 8 h of sleep/)).toBeInTheDocument();
    await user.click(pick("How well did you sleep?", /Good/));
    await user.click(screen.getByRole("button", { name: "Save check-in" }));
    await screen.findByRole("heading", { level: 1, name: "Thanks for checking in" });
    const body = session.api.calls.find((c) => c.path === "/me/check-ins" && c.method === "POST")!
      .body as { sleep: { bedtime: string; wake_time: string; quality: number } };
    expect(body.sleep.quality).toBe(4);
    expect(new Date(body.sleep.wake_time).getTime()).toBeGreaterThan(
      new Date(body.sleep.bedtime).getTime(),
    );
    expect(new Date(body.sleep.wake_time).getTime()).toBeLessThanOrEqual(Date.now());
  });

  it("offers kind words and a way to get support when the API suggests it", async () => {
    renderWithApp(
      <CheckInView />,
      studentSession({
        "POST /me/check-ins": () =>
          json(result({ message: "That sounds really hard.", help_path: "/help" }), 201),
      }),
    );
    const user = userEvent.setup();
    await screen.findByRole("heading", { level: 1 });
    await user.click(pick("Mood", /Very low/));
    await user.click(screen.getByRole("button", { name: "Save check-in" }));
    const note = await screen.findByRole("status");
    expect(note).toHaveTextContent("That sounds really hard.");
    expect(within(note).getByRole("link")).toHaveAttribute("href", "/student/emergency");
  });

  it("keeps the form and shows the reason when saving fails", async () => {
    renderWithApp(
      <CheckInView />,
      studentSession({
        "POST /me/check-ins": () => problem(422, "Wake time can't be in the future."),
      }),
    );
    const user = userEvent.setup();
    await screen.findByRole("heading", { level: 1 });
    await user.click(pick("Mood", /Good/));
    await user.click(screen.getByRole("button", { name: "Save check-in" }));
    expect(await screen.findByText(/Wake time can't be in the future/)).toBeInTheDocument();
    expect(pick("Mood", /Good/)).toBeChecked();
    expect(screen.getByRole("button", { name: "Save check-in" })).toBeEnabled();
  });

  it("has no accessibility violations", async () => {
    const { container } = renderWithApp(<CheckInView />, studentSession());
    await screen.findByRole("heading", { level: 1 });
    await expectNoA11yViolations(container);
  });
});

describe("mood tracking", () => {
  it("creates a mood entry and refreshes the list", async () => {
    let entries = [] as (typeof moodEntry)[];
    const session = studentSession({
      "GET /me/wellness/mood-entries": () => json(entries),
      "GET /me/wellness/trends": () => json({ days: 30, points: [], disclaimer: "x" }),
      "POST /me/check-ins": () => {
        entries = [moodEntry];
        return json(result(), 201);
      },
    });
    renderWithApp(<MoodView />, session);
    const user = userEvent.setup();
    expect(await screen.findByText("No entries yet")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Log mood" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Choose a mood");

    await user.click(pick("How are you feeling?", /Good/));
    await user.click(screen.getByRole("button", { name: "Log mood" }));
    expect(await screen.findByText(/4 of 5, Good/)).toBeInTheDocument();
    const post = session.api.calls.find((c) => c.method === "POST" && c.path === "/me/check-ins")!;
    expect(post.body).toMatchObject({ mood_score: 4 });
  });

  it("charts the last 30 days when there is data, with a table for screen readers", async () => {
    renderWithApp(
      <MoodView />,
      studentSession({
        "GET /me/wellness/mood-entries": () => json([moodEntry]),
        "GET /me/wellness/trends": () =>
          json({
            days: 30,
            points: [trendPoint(-1, { mood: 3 }), trendPoint(0, { mood: 5 })],
            disclaimer: "x",
          }),
      }),
    );
    expect(await screen.findByText(/Average mood: 4.0 out of 5/)).toBeInTheDocument();
    expect(screen.getByRole("table", { name: /Mood by day/ })).toBeInTheDocument();
  });
});

describe("stress tracking", () => {
  it("logs a stress level and what contributed", async () => {
    const session = studentSession({
      "GET /me/wellness/stress-entries": () => json([]),
      "GET /me/wellness/trends": () => json({ days: 30, points: [], disclaimer: "x" }),
      "POST /me/wellness/stress-entries": () =>
        json(
          { id: "s1", stress_level: 4, stressors: ["exams"], logged_at: "2026-10-10T08:00:00Z" },
          201,
        ),
    });
    renderWithApp(<StressView />, session);
    const user = userEvent.setup();
    await screen.findByText("No entries yet");
    await user.click(pick("How stressed do you feel right now?", /^Stressed/));
    await user.click(screen.getByRole("button", { name: "exams" }));
    await user.click(screen.getByRole("button", { name: "Log stress" }));
    await waitFor(() =>
      expect(
        session.api.calls.find((c) => c.method === "POST" && c.path.endsWith("stress-entries"))
          ?.body,
      ).toEqual({
        stress_level: 4,
        stressors: ["exams"],
      }),
    );
  });
});

describe("sleep tracking", () => {
  it("logs bedtime, wake time and quality", async () => {
    const session = studentSession({
      "GET /me/wellness/sleep-entries": () => json([]),
      "GET /me/wellness/trends": () => json({ days: 30, points: [], disclaimer: "x" }),
      "PUT /me/wellness/sleep-entries": ({ body }) =>
        json({ id: "z1", sleep_date: "2026-10-10", duration_minutes: 450, ...(body as object) }),
    });
    renderWithApp(<SleepView />, session);
    const user = userEvent.setup();
    await screen.findByRole("heading", { level: 1, name: "Sleep" });
    await user.click(pick("How well did you sleep?", /Good/));
    await user.click(screen.getByRole("button", { name: /Log sleep/ }));
    await waitFor(() => {
      const put = session.api.calls.find((c) => c.method === "PUT");
      expect(put?.body).toMatchObject({ quality: 4 });
    });
  });
});
