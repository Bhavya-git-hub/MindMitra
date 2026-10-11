import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { GoalsView } from "@/components/student/goals-view";
import { TrendsView } from "@/components/student/wellness-views";
import type { WellnessAnalytics } from "@/lib/api/student-schemas";

import { expectNoA11yViolations } from "../helpers/a11y";
import { json, problem, renderWithApp } from "../helpers/render";
import {
  analyticsWeek,
  emptyAnalytics,
  goal,
  studentSession,
  trendPoint,
} from "../helpers/student-data";

const ANALYTICS = "GET /me/wellness/analytics";

const trends = () =>
  json({
    days: 30,
    points: [trendPoint(-1, { mood: 3, stress: 4 }), trendPoint(0, { mood: 5, stress: 2 })],
    disclaimer: "Self-reported, not a diagnosis.",
  });

/** Three quiet weeks, then two weeks with figures; the current one is still going. */
const filledAnalytics = (): WellnessAnalytics => ({
  ...emptyAnalytics(),
  weeks: [
    analyticsWeek(-4),
    analyticsWeek(-3),
    analyticsWeek(-2),
    analyticsWeek(-1, { wellness_index: 58, mood_avg: 4, days_reported: 4 }),
    analyticsWeek(0, { wellness_index: 71, mood_avg: 4.5, days_reported: 2, partial: true }),
  ],
  wellbeing_checks: [
    {
      completed_at: "2026-09-20T08:00:00Z",
      percent: 48,
      band: { key: "lower", label: "Lower lately", message: "Things have felt heavier." },
    },
    {
      completed_at: "2026-10-05T08:00:00Z",
      percent: 68,
      band: { key: "doing_well", label: "Doing well", message: "Fairly good lately." },
    },
  ],
});

function renderTrends(analytics: () => Response | Promise<Response>) {
  return renderWithApp(
    <TrendsView />,
    studentSession({ "GET /me/wellness/trends": trends, [ANALYTICS]: analytics }),
  );
}

describe("wellness over time (trends page)", () => {
  it("charts the weekly index and the wellbeing checks, each with a data table", async () => {
    const { container } = renderTrends(() => json(filledAnalytics()));
    expect(await screen.findByRole("heading", { name: "Wellness over time" })).toBeInTheDocument();
    const weekly = await screen.findByRole("table", { name: /Weekly wellness index/ });
    // one row per week; a week with no index has an empty cell, the current week says so
    const rows = within(weekly).getAllByRole("row");
    expect(rows).toHaveLength(1 + 5);
    expect(within(weekly).getByRole("cell", { name: "58" })).toBeInTheDocument();
    expect(within(weekly).getByRole("cell", { name: "71" })).toBeInTheDocument();
    expect(within(weekly).getByRole("rowheader", { name: /\(so far\)/ })).toBeInTheDocument();

    expect(screen.getByRole("heading", { name: "Wellbeing checks" })).toBeInTheDocument();
    const checks = screen.getByRole("table", { name: /Wellbeing check results/ });
    expect(within(checks).getByRole("cell", { name: "48" })).toBeInTheDocument();
    expect(within(checks).getByRole("cell", { name: "68" })).toBeInTheDocument();

    await expectNoA11yViolations(container);
  });

  it("asks for eight weeks in the student's time zone", async () => {
    const view = renderTrends(() => json(filledAnalytics()));
    await screen.findByRole("heading", { name: "Wellness over time" });
    const call = view.session.api.calls.find((c) => c.path === "/me/wellness/analytics");
    expect(call?.method).toBe("GET");
    expect(call?.query.get("weeks")).toBe("8");
    expect(call?.query.get("tz")).toBeTruthy();
  });

  it("uses plain, non-clinical wording and repeats the disclaimer", async () => {
    renderTrends(() => json(filledAnalytics()));
    await screen.findByRole("heading", { name: "Wellness over time" });
    expect(screen.getByText(/only describes what you reported/)).toBeInTheDocument();
    expect(
      screen.getByText("These figures describe what you reported. They are not a diagnosis."),
    ).toBeInTheDocument();
    expect(document.body.textContent ?? "").not.toMatch(/depress|disorder|anxiety|diagnosed/i);
  });

  it("says there is not enough data instead of drawing an empty chart", async () => {
    renderTrends(() => json(emptyAnalytics()));
    expect(await screen.findByText("Not enough data yet")).toBeInTheDocument();
    expect(screen.queryByRole("table", { name: /Weekly wellness index/ })).not.toBeInTheDocument();
    expect(screen.getAllByRole("link", { name: "Do a check-in" })[0]).toHaveAttribute(
      "href",
      "/student/check-in",
    );
    // and no checks yet: an invitation, not a chart
    expect(screen.getByText("No checks yet")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Take the check" })).toHaveAttribute(
      "href",
      "/student/assessment",
    );
    expect(
      screen.queryByRole("table", { name: /Wellbeing check results/ }),
    ).not.toBeInTheDocument();
  });

  it("shows a single wellbeing check as a sentence, not a one-point chart", async () => {
    const one = filledAnalytics();
    one.wellbeing_checks = one.wellbeing_checks.slice(1);
    renderTrends(() => json(one));
    expect(await screen.findByText("One check so far: 68% · Doing well")).toBeInTheDocument();
    expect(
      screen.queryByRole("table", { name: /Wellbeing check results/ }),
    ).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Take another check" })).toBeInTheDocument();
  });

  it("shows a loading message while the figures arrive", async () => {
    renderTrends(() => new Promise<Response>(() => {}));
    expect(await screen.findByText("Loading your weekly picture…")).toBeInTheDocument();
    expect(await screen.findByText("4.0 / 5")).toBeInTheDocument(); // the rest of the page is not held up
  });

  it("explains a failure on its own and lets the student retry", async () => {
    let fail = true;
    renderTrends(() => (fail ? problem(503, "Down") : json(filledAnalytics())));
    const user = userEvent.setup();
    const alert = await screen.findByRole("alert");
    expect(within(alert).getByText("Something didn't load")).toBeInTheDocument();
    // the other trends still render
    expect(screen.getByText("4.0 / 5")).toBeInTheDocument();

    fail = false;
    await user.click(within(alert).getByRole("button", { name: "Try again" }));
    expect(await screen.findByRole("table", { name: /Weekly wellness index/ })).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});

const goalAnalytics = (extra: Partial<WellnessAnalytics["goals"]> = {}): WellnessAnalytics => {
  const base = emptyAnalytics();
  return {
    ...base,
    goals: {
      ...base.goals,
      active: 2,
      completed: 3,
      other: 1,
      average_progress_percent: 58.3,
      by_category: [
        { category: "movement", active: 0, completed: 2, average_progress_percent: null },
        { category: "sleep", active: 2, completed: 1, average_progress_percent: 58.3 },
      ],
      completed_by_week: base.goals.completed_by_week.map((w, i) => ({
        ...w,
        completed: [0, 2, 0, 1][i] ?? 0,
      })),
      ...extra,
    },
  };
};

function renderGoals(
  analytics: () => Response | Promise<Response>,
  extra: Parameters<typeof studentSession>[0] = {},
) {
  return renderWithApp(
    <GoalsView />,
    studentSession({ "GET /me/goals": () => json([goal()]), [ANALYTICS]: analytics, ...extra }),
  );
}

describe("goal progress (goals page)", () => {
  it("shows the counts, average progress, areas and a chart of goals completed each week", async () => {
    const { container } = renderGoals(() => json(goalAnalytics()));
    expect(await screen.findByRole("heading", { name: "Goal progress" })).toBeInTheDocument();
    expect(screen.getByText("Completed goals")).toBeInTheDocument();
    expect(screen.getByText("58%")).toBeInTheDocument();
    expect(screen.getByText("Active goals").nextElementSibling).toHaveTextContent("2");
    expect(screen.getByText("Completed goals").nextElementSibling).toHaveTextContent("3");

    const areas = screen.getByRole("heading", { name: "By area" })
      .nextElementSibling as HTMLElement;
    expect(within(areas).getByText("Sleep")).toBeInTheDocument();
    expect(
      within(areas).getByText(/2 active · 1 completed · 58% average progress/),
    ).toBeInTheDocument();
    expect(within(areas).getByText(/0 active · 2 completed$/)).toBeInTheDocument();

    const chart = screen.getByRole("table", { name: /Goals completed each week/ });
    expect(within(chart).getAllByRole("row")).toHaveLength(1 + 4);
    expect(within(chart).getByRole("cell", { name: "2" })).toBeInTheDocument();
    expect(within(chart).getByRole("rowheader", { name: /\(so far\)/ })).toBeInTheDocument();
    expect(screen.getByText(/not how it changed over time/)).toBeInTheDocument();
    await expectNoA11yViolations(container);
  });

  it("asks the same eight-week analytics endpoint as the trends page", async () => {
    const view = renderGoals(() => json(goalAnalytics()));
    await screen.findByRole("heading", { name: "Goal progress" });
    const call = view.session.api.calls.find((c) => c.path === "/me/wellness/analytics");
    expect(call?.query.get("weeks")).toBe("8");
  });

  it("says so when no goals were finished in the period, without an empty chart", async () => {
    renderGoals(() =>
      json(
        goalAnalytics({
          completed: 0,
          completed_by_week: emptyAnalytics().goals.completed_by_week,
        }),
      ),
    );
    expect(
      await screen.findByText(/No goals finished in the last 4 weeks yet/),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("table", { name: /Goals completed each week/ }),
    ).not.toBeInTheDocument();
  });

  it("explains how to get an average when no goal has a target", async () => {
    renderGoals(() => json(goalAnalytics({ average_progress_percent: null, by_category: [] })));
    expect(await screen.findByText("Add a target number to see this")).toBeInTheDocument();
    expect(screen.getByText("Average progress").nextElementSibling).toHaveTextContent("—");
    expect(screen.queryByRole("heading", { name: "By area" })).not.toBeInTheDocument();
  });

  it("stays out of the way when there are no goals at all", async () => {
    renderWithApp(
      <GoalsView />,
      studentSession({
        "GET /me/goals": () => json([]),
        [ANALYTICS]: () => json(emptyAnalytics()),
      }),
    );
    expect(await screen.findByText("No goals yet")).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Goal progress" })).not.toBeInTheDocument();
  });

  it("shows a loading message without holding up the goals", async () => {
    renderGoals(() => new Promise<Response>(() => {}));
    expect(await screen.findByText("Loading your goal figures…")).toBeInTheDocument();
    expect(await screen.findByRole("progressbar", { name: /Wind down/ })).toBeInTheDocument();
  });

  it("explains a failure and recovers on retry", async () => {
    let fail = true;
    renderGoals(() => (fail ? problem(500, "Broken") : json(goalAnalytics())));
    const user = userEvent.setup();
    const alert = await screen.findByRole("alert");
    expect(within(alert).getByText("Something didn't load")).toBeInTheDocument();
    expect(screen.getByRole("progressbar", { name: /Wind down/ })).toBeInTheDocument(); // goals still there
    fail = false;
    await user.click(within(alert).getByRole("button", { name: "Try again" }));
    expect(await screen.findByRole("heading", { name: "Goal progress" })).toBeInTheDocument();
  });

  it("refreshes the figures after a goal changes", async () => {
    let asked = 0;
    const view = renderGoals(
      () => {
        asked += 1;
        return json(goalAnalytics());
      },
      { "PATCH /me/goals/goal-1": () => json(goal({ status: "completed" })) },
    );
    const user = userEvent.setup();
    await screen.findByRole("heading", { name: "Goal progress" });
    expect(asked).toBe(1);
    await user.click(screen.getByRole("button", { name: "Mark as done" }));
    await waitFor(() => expect(asked).toBe(2));
    expect(
      view.session.api.calls.filter((c) => c.path === "/me/goals" && c.method === "GET").length,
    ).toBeGreaterThanOrEqual(2);
  });
});
