import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AnalyticsView, OversightView } from "@/components/admin/insights-views";

import { expectNoA11yViolations } from "../helpers/a11y";
import { adminSession, oversight, platformAnalytics } from "../helpers/admin-data";
import {
  quietServiceAnalytics,
  serviceAnalytics,
  suppressedGroup,
} from "../helpers/admin-usage-data";
import { navigation } from "../helpers/navigation";
import { json, problem, renderWithApp } from "../helpers/render";

beforeEach(() => navigation.reset());
afterEach(() => vi.restoreAllMocks());

const routes = (services = () => json(serviceAnalytics())) => ({
  "GET /admin/analytics": () => json(platformAnalytics()),
  "GET /admin/analytics/services": services,
});

/** The cells of a table row, by its row header. */
const rowOf = (table: HTMLElement, name: string) =>
  within(within(table).getByRole("rowheader", { name }).closest("tr")!).getAllByRole("cell");
/** The big number on a stat card, found by its label. */
const stat = (label: string) =>
  screen.getByText(label, { selector: "p" }).nextElementSibling as HTMLElement;
const texts = (cells: HTMLElement[]) => cells.map((c) => c.textContent);

describe("weekly counts are charted, with the numbers kept in an accessible table", () => {
  it("charts appointments booked and alerts raised", async () => {
    const { container } = renderWithApp(<AnalyticsView />, adminSession(routes()));
    const booked = await screen.findByRole("table", { name: "Appointments booked each week" });
    expect(rowOf(booked, "Sep 21")).toHaveLength(1);
    expect(texts(rowOf(booked, "Sep 21"))).toEqual(["14"]);
    expect(texts(rowOf(booked, "Sep 28"))).toEqual(["Fewer than 5"]);
    const alerts = screen.getByRole("table", { name: "Safety alerts raised each week" });
    expect(texts(rowOf(alerts, "Sep 21"))).toEqual(["0"]);
    expect(texts(rowOf(alerts, "Sep 28"))).toEqual(["Fewer than 5"]);
    // each chart is a figure named after what it shows
    expect(screen.getByRole("figure", { name: "Appointments booked each week" })).toBeVisible();
    await screen.findByText("Platform usage");
    await expectNoA11yViolations(container);
  });

  it("charts the weeks scheduled on the oversight page", async () => {
    const session = adminSession({ "GET /admin/appointments/oversight": () => json(oversight()) });
    renderWithApp(<OversightView />, session);
    const scheduled = await screen.findByRole("table", {
      name: "Appointments scheduled each week",
    });
    expect(texts(rowOf(scheduled, "Sep 21"))).toEqual(["12"]);
    expect(texts(rowOf(scheduled, "Sep 28"))).toEqual(["Fewer than 5"]);
    expect(screen.getByRole("figure", { name: "Appointments scheduled each week" })).toBeVisible();
  });
});

describe("platform usage", () => {
  it("shows window totals and weekly charts, with hidden counts as words", async () => {
    const { container } = renderWithApp(<AnalyticsView />, adminSession(routes()));
    await screen.findByRole("heading", { name: "Platform usage" });
    expect(stat("Check-ins")).toHaveTextContent("120");
    expect(stat("Students who logged something")).toHaveTextContent("47");
    expect(stat("Messages with therapists")).toHaveTextContent("Fewer than 5");

    const activity = screen.getByRole("table", {
      name: "Check-ins, active students and sign-ins each week",
    });
    expect(
      within(activity)
        .getAllByRole("columnheader")
        .map((c) => c.textContent),
    ).toEqual(["week", "Check-ins", "Active students", "Sign-ins"]);
    expect(texts(rowOf(activity, "Sep 14"))).toEqual(["120", "45", "200"]);
    expect(texts(rowOf(activity, "Sep 21"))).toEqual(["Fewer than 5", "Fewer than 5", "160"]);
    const messages = screen.getByRole("table", { name: "Messages each week" });
    expect(texts(rowOf(messages, "Sep 14"))).toEqual(["310", "88"]);
    // zero is zero, never "fewer than 5"
    expect(texts(rowOf(messages, "Sep 21"))).toEqual(["0", "Fewer than 5"]);
    await expectNoA11yViolations(container);
  });
});

describe("counselling utilisation", () => {
  it("shows booked against offered hours and the share by session type", async () => {
    const { container } = renderWithApp(<AnalyticsView />, adminSession(routes()));
    expect(await screen.findByRole("heading", { name: "Counselling utilisation" })).toBeVisible();
    expect(stat("Time booked")).toHaveTextContent("55%");
    expect(screen.getByText("9.7 h of 17.3 h offered")).toBeVisible();
    expect(stat("Cancelled appointments")).toHaveTextContent("About 35%");
    expect(stat("No-shows")).toHaveTextContent("A few");

    const hours = screen.getByRole("table", { name: "Hours offered and booked each week" });
    expect(texts(rowOf(hours, "Sep 14"))).toEqual(["12.3", "7.7"]);
    expect(texts(rowOf(hours, "Sep 21"))).toEqual(["5", "Fewer than 5"]);
    const percent = screen.getByRole("table", {
      name: "Share of offered time that was booked each week (%)",
    });
    expect(texts(rowOf(percent, "Sep 14"))).toEqual(["60"]);
    expect(texts(rowOf(percent, "Sep 21"))).toEqual(["Fewer than 5"]);

    const modes = screen.getByRole("table", { name: "Counselling utilisation by session type" });
    expect(texts(rowOf(modes, "Video call"))).toEqual([
      "15",
      "8",
      "55%",
      "Not enough people",
      "Nearly all",
    ]);
    expect(texts(rowOf(modes, "In person"))[2]).toBe("No hours offered");
    expect(texts(rowOf(modes, "Phone call"))[1]).toBe("Fewer than 5");
    await expectNoA11yViolations(container);
  });

  it("says so when no hours were offered", async () => {
    renderWithApp(<AnalyticsView />, adminSession(routes(() => json(quietServiceAnalytics()))));
    expect(
      await screen.findByText("No counselling hours were offered in this period."),
    ).toBeVisible();
    expect(screen.queryByRole("table", { name: "Hours offered and booked each week" })).toBeNull();
  });
});

describe("intervention engagement", () => {
  it("shows groups with enough people and 'Too few people to show' for the rest", async () => {
    const { container } = renderWithApp(<AnalyticsView />, adminSession(routes()));
    expect(await screen.findByRole("heading", { name: "Intervention engagement" })).toBeVisible();

    const areas = screen.getByRole("table", { name: "Engagement by problem area" });
    expect(texts(rowOf(areas, "Stress"))).toEqual(["60", "25", "20", "5", "15", "Fewer than 5"]);
    // a quiet cell inside a shown group is a hidden count, not a suppressed group
    expect(texts(rowOf(areas, "Sleep disruption"))[2]).toBe("Fewer than 5");
    for (const name of ["Academic burnout", "Mood", "Other"]) {
      expect(texts(rowOf(areas, name))).toEqual(["Too few people to show"]);
    }
    const sources = screen.getByRole("table", {
      name: "Engagement by where the suggestion came from",
    });
    expect(texts(rowOf(sources, "Rule-based"))[0]).toBe("120");
    expect(texts(rowOf(sources, "Model-based"))).toEqual(["Too few people to show"]);
    expect(texts(rowOf(sources, "Made by a therapist"))).toEqual(["Too few people to show"]);

    // the chart carries only the areas that may be shown
    const chart = screen.getByRole("table", { name: "Suggestions by problem area" });
    expect(
      within(chart)
        .getAllByRole("rowheader")
        .map((r) => r.textContent),
    ).toEqual(["Stress", "Sleep disruption"]);
    expect(texts(rowOf(chart, "Sleep disruption"))).toEqual(["25", "Fewer than 5", "Fewer than 5"]);

    expect(stat("Students who finished a suggestion")).toHaveTextContent("About 45%");
    expect(stat("Students who found one helpful")).toHaveTextContent("Not enough people");
    expect(screen.getByText(/Box breathing:/)).toHaveTextContent("at least 15 students");
    expect(screen.getByText(/Short walk:/)).toHaveTextContent("at least 5 students");
    await expectNoA11yViolations(container);
  });

  it("explains an empty chart when every group is too small", async () => {
    renderWithApp(<AnalyticsView />, adminSession(routes(() => json(quietServiceAnalytics()))));
    expect(await screen.findByText(/no problem area has 5 different students yet/)).toBeVisible();
    expect(screen.queryByRole("table", { name: "Suggestions by problem area" })).toBeNull();
    expect(screen.getByText("No single suggestion has reached 5 students yet.")).toBeVisible();
    const areas = screen.getByRole("table", { name: "Engagement by problem area" });
    expect(within(areas).getAllByText("Too few people to show")).toHaveLength(2);
  });

  it("names nobody and quotes nothing", async () => {
    const data = serviceAnalytics();
    data.engagement.by_problem_area.push(suppressedGroup("career_anxiety"));
    const { container } = renderWithApp(<AnalyticsView />, adminSession(routes(() => json(data))));
    await screen.findByRole("heading", { name: "Intervention engagement" });
    expect(container.textContent).not.toMatch(/@|student_id|full_name|rationale/);
    expect(container.textContent).toContain("Nothing here describes an individual.");
  });
});

describe("loading, errors and the week selector", () => {
  it("keeps the rest of the page when the service figures fail, and retries", async () => {
    const user = userEvent.setup();
    let fail = true;
    const session = adminSession(
      routes(() => (fail ? problem(500, "Could not read usage.") : json(serviceAnalytics()))),
    );
    renderWithApp(<AnalyticsView />, session);
    // the older sections are unaffected
    expect(await screen.findByText("Student wellbeing")).toBeVisible();
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Something didn't load");
    fail = false;
    await user.click(within(alert).getByRole("button", { name: /try again/i }));
    expect(await screen.findByRole("heading", { name: "Platform usage" })).toBeVisible();
  });

  it("asks for the chosen window again", async () => {
    const user = userEvent.setup();
    const session = adminSession(routes(() => json(serviceAnalytics())));
    renderWithApp(<AnalyticsView />, session);
    await screen.findByRole("heading", { name: "Platform usage" });
    const first = session.api.calls.filter((c) => c.path === "/admin/analytics/services");
    expect(first.map((c) => c.query.get("weeks"))).toEqual(["8"]);

    await user.click(screen.getByRole("button", { name: "12 weeks" }));
    await waitFor(() =>
      expect(
        session.api.calls
          .filter((c) => c.path === "/admin/analytics/services")
          .map((c) => c.query.get("weeks")),
      ).toEqual(["8", "12"]),
    );
    expect(
      session.api.calls
        .filter((c) => c.path === "/admin/analytics")
        .map((c) => c.query.get("weeks")),
    ).toEqual(["8", "12"]);
  });
});
