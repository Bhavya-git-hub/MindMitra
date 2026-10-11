import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { AnalyticsView } from "@/components/therapist/analytics-view";
import { NAVIGATION } from "@/lib/navigation";

import { expectNoA11yViolations } from "../helpers/a11y";
import { json, problem, renderWithApp } from "../helpers/render";
import {
  analytics,
  emptyAnalytics,
  pendingProfile,
  profile,
  therapistSession,
} from "../helpers/therapist-data";

const ANALYTICS = "GET /therapist/analytics";
const verified = { "GET /therapist/profile": () => json(profile()) };

function renderAnalytics(answer: () => Response | Promise<Response>) {
  return renderWithApp(<AnalyticsView />, therapistSession({ ...verified, [ANALYTICS]: answer }));
}

const heading = (name: string) => screen.findByRole("heading", { name });

describe("therapist analytics", () => {
  it("shows the four sections, each chart with an accessible table", async () => {
    const { container } = renderAnalytics(() => json(analytics()));
    expect(await screen.findByRole("heading", { level: 1, name: "Analytics" })).toBeVisible();
    for (const name of ["Your caseload", "Appointments", "Interventions", "Risk alerts"]) {
      expect(await heading(name)).toBeInTheDocument();
    }

    const mood = await screen.findByRole("table", { name: "Mood and stress by week" });
    expect(within(mood).getAllByRole("row")).toHaveLength(1 + 4);
    expect(within(mood).getByRole("cell", { name: "4" })).toBeInTheDocument();
    expect(await screen.findByRole("table", { name: "Sleep by week" })).toBeInTheDocument();

    const weekly = screen.getByRole("table", { name: "Appointments each week" });
    expect(
      within(weekly)
        .getAllByRole("columnheader")
        .map((c) => c.textContent),
    ).toEqual(["week", "All", "Completed", "Did not attend", "Cancelled"]);
    expect(screen.getByRole("table", { name: "Suggestions by progress" })).toBeInTheDocument();
    expect(screen.getByRole("table", { name: "Follow-ups by progress" })).toBeInTheDocument();
    expect(screen.getByRole("table", { name: "Alerts raised each week" })).toBeInTheDocument();
    const severity = screen.getByRole("table", { name: "Alerts by priority" });
    expect(within(severity).getByRole("rowheader", { name: "High priority" })).toBeInTheDocument();
    await expectNoA11yViolations(container);
  });

  it("states caseload, rates, follow-up figures and the median response time in words", async () => {
    renderAnalytics(() => json(analytics()));
    await heading("Your caseload");
    expect(screen.getByText("of 5 on your caseload")).toBeInTheDocument();
    expect(screen.getByText("67%")).toBeInTheDocument();
    expect(screen.getByText("11%")).toBeInTheDocument();
    expect(screen.getByText("22%")).toBeInTheDocument();
    expect(screen.getAllByText("of 9 that finished")).toHaveLength(3);
    expect(
      screen.getByText(/How you met: Video call 7 · In person 2 · Phone call 1/),
    ).toBeInTheDocument();
    expect(screen.getByText("40%")).toBeInTheDocument(); // suggestions completed
    expect(screen.getByText("Still open after the due date")).toBeInTheDocument();
    expect(screen.getByText("1 h 15 min")).toBeInTheDocument(); // median 75 minutes
    expect(screen.getByText(/By type: Check in 3 · Book a session 1/)).toBeInTheDocument();
    expect(screen.getByText(/Counts and averages only. Self-reported/)).toBeInTheDocument();
  });

  it("uses plain, non-clinical wording and never names a student", async () => {
    const { container } = renderAnalytics(() => json(analytics()));
    await heading("Risk alerts");
    const text = container.textContent ?? "";
    expect(text.replace(/not a diagnosis/gi, "")).not.toMatch(/diagnos|disorder|patient|treat/i);
    expect(text).toMatch(/never a conclusion about a student/);
    expect(text).not.toMatch(/Aarini|@/);
  });

  it("asks for 8 weeks first and fetches again when another window is chosen", async () => {
    const { session } = renderAnalytics(() => json(analytics()));
    await heading("Your caseload");
    const first = session.api.calls.filter((c) => c.path === "/therapist/analytics");
    expect(first).toHaveLength(1);
    expect(first[0]?.query.get("weeks")).toBe("8");
    expect(first[0]?.query.get("tz")).toBeTruthy();

    expect(screen.getByRole("button", { name: "8 weeks", pressed: true })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "12 weeks" }));
    await waitFor(() => {
      const calls = session.api.calls.filter((c) => c.path === "/therapist/analytics");
      expect(calls.map((c) => c.query.get("weeks"))).toEqual(["8", "12"]);
    });
    await userEvent.click(screen.getByRole("button", { name: "4 weeks" }));
    await waitFor(() => {
      const calls = session.api.calls.filter((c) => c.path === "/therapist/analytics");
      expect(calls.map((c) => c.query.get("weeks"))).toEqual(["8", "12", "4"]);
    });
    expect(await heading("Your caseload")).toBeInTheDocument();
  });

  it("explains an empty caseload instead of drawing empty charts", async () => {
    const { container } = renderAnalytics(() => json(emptyAnalytics()));
    expect(await screen.findByText("No shared check-ins yet")).toBeInTheDocument();
    expect(screen.getByText("No appointments in these weeks")).toBeInTheDocument();
    expect(
      screen.getByText("You have not sent any suggestions in these weeks."),
    ).toBeInTheDocument();
    expect(screen.getByText("You have not set any follow-ups in these weeks.")).toBeInTheDocument();
    expect(screen.getByText("No alerts in these weeks")).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    expect(screen.getByText("No students yet")).toBeInTheDocument();
    await expectNoA11yViolations(container);
  });

  it("shows dashes, not zeros, for rates that cannot be worked out", async () => {
    const base = analytics();
    renderAnalytics(() =>
      json(
        analytics({
          appointments: {
            ...base.appointments,
            by_status: { requested: 1, confirmed: 1, completed: 0, cancelled: 0, no_show: 0 },
            rates: { completion: null, no_show: null, cancellation: null },
          },
        }),
      ),
    );
    await heading("Appointments");
    expect(screen.getAllByText("Nothing has finished yet")).toHaveLength(3);
    expect(screen.queryByText("0%")).not.toBeInTheDocument();
  });

  it("says when students share but nothing was logged in the weeks shown", async () => {
    const base = analytics();
    renderAnalytics(() =>
      json(
        analytics({
          caseload: {
            ...base.caseload,
            weekly: base.caseload.weekly.map((w) => ({
              ...w,
              students_reporting: 0,
              mood_avg: null,
              stress_avg: null,
              sleep_hours_avg: null,
            })),
          },
        }),
      ),
    );
    expect(await screen.findByText("No check-ins in these weeks")).toBeInTheDocument();
    expect(screen.queryByRole("table", { name: "Sleep by week" })).not.toBeInTheDocument();
  });

  it("shows a loading state, then a calm error that can be retried", async () => {
    let attempt = 0;
    const { container } = renderAnalytics(() => {
      attempt += 1;
      return attempt === 1 ? problem(500, "Something went wrong on our side.") : json(analytics());
    });
    expect(container.querySelector('[aria-busy="true"], [role="status"]')).not.toBeNull();
    const retry = await screen.findByRole("button", { name: /try again|retry/i });
    expect(screen.getByText(/Something went wrong/)).toBeInTheDocument();
    await userEvent.click(retry);
    expect(await heading("Your caseload")).toBeInTheDocument();
    expect(attempt).toBe(2);
  });

  it("stays closed and asks for nothing until the therapist is verified", async () => {
    const session = therapistSession({
      "GET /therapist/profile": () => json(pendingProfile()),
      [ANALYTICS]: () => json(analytics()),
    });
    renderWithApp(<AnalyticsView />, session);
    expect(await screen.findByText(/once an administrator has verified/)).toBeInTheDocument();
    expect(session.api.calls.some((c) => c.path === "/therapist/analytics")).toBe(false);
  });

  it("is in the therapist's menu", () => {
    const item = NAVIGATION.therapist.find((i) => i.href === "/therapist/analytics");
    expect(item?.label).toBe("Analytics");
  });
});
