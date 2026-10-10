import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { DashboardView } from "@/components/student/dashboard-view";

import { expectNoA11yViolations } from "../helpers/a11y";
import { json, problem, renderWithApp } from "../helpers/render";
import { appointment, dashboard, filledDashboard, studentSession } from "../helpers/student-data";

describe("student dashboard", () => {
  it("shows today's mood, stress and sleep, the next appointment, trends and ideas", async () => {
    const { container } = renderWithApp(
      <DashboardView />,
      studentSession({ "GET /me/dashboard": () => json(filledDashboard()) }),
    );
    expect(await screen.findByRole("heading", { level: 1, name: "Hello, Asha" })).toBeVisible();

    expect(screen.getByText("4 / 5")).toBeInTheDocument(); // mood today
    expect(screen.getByText("Feeling good")).toBeInTheDocument();
    expect(screen.getByText("2 / 5")).toBeInTheDocument(); // stress today
    expect(screen.getByText("Mostly calm")).toBeInTheDocument();
    expect(screen.getByText("7 h 30 min")).toBeInTheDocument(); // sleep last night
    expect(screen.getByText("68%")).toBeInTheDocument(); // wellbeing check

    expect(screen.getByRole("heading", { name: "Next appointment" })).toBeInTheDocument();
    expect(screen.getByText(/Dr\. Priya Nair/)).toBeInTheDocument();
    expect(screen.getByText("Try a short breathing exercise")).toBeInTheDocument();
    expect(screen.getByRole("figure", { name: /Mood and stress this week/ })).toBeInTheDocument();
    expect(screen.getAllByText(/not a diagnosis/i).length).toBeGreaterThan(0);
    expect(screen.getByText(/You've checked in today/)).toBeInTheDocument();

    await expectNoA11yViolations(container);
  });

  it("asks for a first check-in when nothing is logged, without inventing numbers", async () => {
    const { container } = renderWithApp(
      <DashboardView />,
      studentSession({ "GET /me/dashboard": () => json(dashboard()) }),
    );
    await screen.findByRole("heading", { level: 1 });
    expect(screen.getByRole("link", { name: "Check in now" })).toHaveAttribute(
      "href",
      "/student/check-in",
    );
    expect(screen.getAllByText("—").length).toBeGreaterThanOrEqual(3);
    expect(screen.getByText(/No check-in yet/)).toBeInTheDocument();
    expect(screen.getByText("Nothing to chart yet")).toBeInTheDocument();
    expect(screen.getByText(/No suggestions right now/)).toBeInTheDocument();
    await expectNoA11yViolations(container);
  });

  it("explains a request that is still waiting for the therapist", async () => {
    renderWithApp(
      <DashboardView />,
      studentSession({
        "GET /me/dashboard": () =>
          json(dashboard({ upcoming_appointment: appointment({ status: "requested" }) })),
      }),
    );
    expect(await screen.findByText("Waiting for confirmation")).toBeInTheDocument();
  });

  it("shows a calm error with the reference and retries on request", async () => {
    let calls = 0;
    renderWithApp(
      <DashboardView />,
      studentSession({
        "GET /me/dashboard": () => {
          calls += 1;
          return calls === 1 ? problem(500, "Something went wrong") : json(filledDashboard());
        },
      }),
    );
    const alert = await screen.findByRole("alert");
    expect(within(alert).getByText(/req-1/)).toBeInTheDocument();
    await userEvent.setup().click(screen.getByRole("button", { name: /try again/i }));
    await waitFor(() => expect(screen.getByText("Feeling good")).toBeInTheDocument());
  });

  it("only asks for the signed-in student's own data (no ids in the request)", async () => {
    const session = studentSession({ "GET /me/dashboard": () => json(dashboard()) });
    renderWithApp(<DashboardView />, session);
    await screen.findByRole("heading", { level: 1 });
    const paths = session.api.calls.map((c) => c.path).filter((p) => p !== "/auth/refresh");
    expect(paths).toContain("/me/dashboard");
    expect(paths.every((p) => p === "/me" || p.startsWith("/me/"))).toBe(true);
  });
});
