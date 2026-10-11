import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { GoalsView } from "@/components/student/goals-view";
import { RecommendationsView } from "@/components/student/recommendations-view";
import { ResourceDetailView, ResourcesView } from "@/components/student/resources-views";
import { AssessmentView, TrendsView, WellnessView } from "@/components/student/wellness-views";

import { expectNoA11yViolations } from "../helpers/a11y";
import { json, problem, renderWithApp } from "../helpers/render";
import {
  filledDashboard,
  goal,
  instrument,
  recommendation,
  resource,
  studentSession,
  trendPoint,
} from "../helpers/student-data";

const trends = (
  days: number,
  points = [
    trendPoint(-1, { mood: 3, stress: 4, sleep_minutes: 420 }),
    trendPoint(0, { mood: 5, stress: 2 }),
  ],
) => json({ days, points, disclaimer: "Self-reported, not a diagnosis." });

describe("wellness dashboard", () => {
  it("brings mood, stress, sleep and the wellbeing check together with a link to log each", async () => {
    const { container } = renderWithApp(
      <WellnessView />,
      studentSession({
        "GET /me/wellness/summary": () => json(filledDashboard()),
        "GET /me/wellness/trends": () => trends(30),
      }),
    );
    expect(await screen.findByText("Feeling good")).toBeInTheDocument();
    expect(screen.getByText("68%")).toBeInTheDocument();
    expect(screen.getByText(/5 check-ins in the last 7 days/)).toBeInTheDocument();
    expect(screen.getByText("calm")).toBeInTheDocument();
    for (const [name, href] of [
      ["Mood", "/student/mood"],
      ["Stress", "/student/stress"],
      ["Sleep", "/student/sleep"],
      ["Wellbeing check", "/student/assessment"],
    ] as const) {
      expect(screen.getByRole("link", { name })).toHaveAttribute("href", href);
    }
    await expectNoA11yViolations(container);
  });
});

describe("personal trends", () => {
  it("shows averages and charts, and switches range", async () => {
    const asked: (string | null)[] = [];
    renderWithApp(
      <TrendsView />,
      studentSession({
        "GET /me/wellness/trends": ({ query }) => {
          asked.push(query.get("days"));
          return trends(Number(query.get("days")));
        },
      }),
    );
    const user = userEvent.setup();
    expect(await screen.findByText("4.0 / 5")).toBeInTheDocument(); // average mood
    expect(
      screen.getByRole("table", { name: /Mood and energy, last 30 days/ }),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "30 days" })).toHaveAttribute("aria-pressed", "true");

    await user.click(screen.getByRole("button", { name: "90 days" }));
    await waitFor(() => expect(asked).toContain("90"));
    expect(
      await screen.findByRole("table", { name: /Mood and energy, last 90 days/ }),
    ).toBeInTheDocument();
  });

  it("invites a first check-in instead of drawing empty charts", async () => {
    renderWithApp(
      <TrendsView />,
      studentSession({ "GET /me/wellness/trends": () => trends(30, [trendPoint(0)]) }),
    );
    expect(await screen.findByText("Nothing to chart yet")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Do a check-in" })).toHaveAttribute(
      "href",
      "/student/check-in",
    );
  });
});

describe("wellness assessment", () => {
  function setup(extra: Parameters<typeof studentSession>[0] = {}) {
    const session = studentSession({
      "GET /me/wellness/assessment": () => json(instrument()),
      "GET /me/wellness/assessments": () => json([]),
      "POST /me/wellness/assessments": () =>
        json(
          {
            id: "as-2",
            score: 15,
            max_score: 25,
            percent: 60,
            band: { key: "mixed", label: "Mixed", message: "Some days are better than others." },
            completed_at: "2026-10-10T08:00:00Z",
          },
          201,
        ),
      ...extra,
    });
    const view = renderWithApp(<AssessmentView />, session);
    return { ...view, session };
  }

  it("won't submit until every question is answered", async () => {
    const { session } = setup();
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "See my result" }));
    expect(screen.getByText(/answer every question/)).toBeInTheDocument();
    await user.click(screen.getAllByLabelText("All of the time")[0]!);
    await user.click(screen.getByRole("button", { name: "See my result" }));
    expect(screen.getByText(/answer every question/)).toBeInTheDocument();
    expect(
      session.api.calls.some((c) => c.method === "POST" && c.path.includes("assessments")),
    ).toBe(false);
  });

  it("sends the answers and shows a gentle, non-diagnostic result", async () => {
    const { session, container } = setup();
    const user = userEvent.setup();
    await screen.findByRole("button", { name: "See my result" });
    await user.click(screen.getAllByLabelText("All of the time")[0]!);
    await user.click(screen.getAllByLabelText("More than half the time")[1]!);
    await user.click(screen.getByRole("button", { name: "See my result" }));

    expect(await screen.findByRole("heading", { name: "Your result" })).toBeInTheDocument();
    expect(screen.getByText(/not a diagnosis/i)).toBeInTheDocument();
    expect(
      session.api.calls.find((c) => c.method === "POST" && c.path.includes("assessments"))?.body,
    ).toEqual({
      responses: { q1: 5, q2: 3 },
    });
    await expectNoA11yViolations(container);
  });
});

describe("wellness goals", () => {
  it("creates a goal with an optional target", async () => {
    const created: unknown[] = [];
    let goals = [] as ReturnType<typeof goal>[];
    renderWithApp(
      <GoalsView />,
      studentSession({
        "GET /me/goals": () => json(goals),
        "POST /me/goals": ({ body }) => {
          created.push(body);
          goals = [goal()];
          return json(goal(), 201);
        },
      }),
    );
    const user = userEvent.setup();
    expect(await screen.findByText("No goals yet")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Add goal" }));
    expect(screen.getByText(/at least 3 letters/)).toBeInTheDocument();
    expect(created).toHaveLength(0);

    await user.type(
      screen.getByLabelText("What would you like to work on?"),
      "Wind down before midnight",
    );
    await user.type(screen.getByLabelText("Target number (optional)"), "5");
    await user.type(screen.getByLabelText("Measured in (optional)"), "nights");
    await user.click(screen.getByRole("button", { name: "Add goal" }));
    expect(await screen.findByRole("progressbar", { name: /Wind down/ })).toHaveAttribute(
      "aria-valuenow",
      "40",
    );
    expect(created).toEqual([
      { title: "Wind down before midnight", category: "sleep", target_value: 5, unit: "nights" },
    ]);
  });

  it("updates progress and can mark a goal done, pause it or let it go", async () => {
    const patches: unknown[] = [];
    const { container } = renderWithApp(
      <GoalsView />,
      studentSession({
        "GET /me/goals": () => json([goal()]),
        "PATCH /me/goals/goal-1": ({ body }) => {
          patches.push(body);
          return json(goal());
        },
      }),
    );
    const user = userEvent.setup();
    const progress = await screen.findByLabelText(/Progress so far/);
    await user.clear(progress);
    await user.type(progress, "4");
    await user.click(screen.getByRole("button", { name: "Save progress" }));
    await user.click(screen.getByRole("button", { name: "Pause" }));
    await user.click(screen.getByRole("button", { name: "Mark as done" }));
    await user.click(screen.getByRole("button", { name: "Let it go" }));
    await waitFor(() => expect(patches).toHaveLength(4));
    expect(patches).toEqual([
      { current_value: 4 },
      { status: "paused" },
      { status: "completed" },
      { status: "abandoned" },
    ]);
    await expectNoA11yViolations(container);
  });

  it("separates finished goals and doesn't offer to change them", async () => {
    renderWithApp(
      <GoalsView />,
      studentSession({ "GET /me/goals": () => json([goal({ status: "completed", id: "g2" })]) }),
    );
    expect(await screen.findByRole("heading", { name: "Finished" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Save progress" })).not.toBeInTheDocument();
  });
});

const preferences = (extra = {}) => ({
  preferred_formats: [],
  max_minutes: null,
  muted_areas: [],
  use_indicators: true,
  available_formats: ["article", "video", "exercise", "audio", "service"],
  available_areas: ["academic_burnout", "sleep_disruption", "counselling"],
  ...extra,
});

describe("recommendations", () => {
  it("shows why each suggestion was made, and lets the student set it aside or finish it", async () => {
    const responses: unknown[] = [];
    const { container } = renderWithApp(
      <RecommendationsView />,
      studentSession({
        "GET /me/recommendations": () => json([recommendation()]),
        "GET /me/recommendations/history": () =>
          json([
            recommendation(),
            recommendation({
              id: "rec-2",
              title: "Old idea",
              rationale: "From last month.",
              status: "completed",
            }),
          ]),
        "GET /me/recommendations/preferences": () => json(preferences()),
        "PATCH /me/recommendations/rec-1": ({ body }) => {
          responses.push(body);
          return json(recommendation({ status: "dismissed" }));
        },
      }),
    );
    const user = userEvent.setup();
    expect(
      await screen.findByText("You mentioned feeling stressed this week."),
    ).toBeInTheDocument();
    expect(await screen.findByRole("heading", { name: "Earlier" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Not for me" }));
    await waitFor(() => expect(responses).toEqual([{ status: "dismissed" }]));
    await expectNoA11yViolations(container);
  });

  it("lets the student say a suggestion was helpful, and take it back", async () => {
    const calls: string[] = [];
    let rated = false;
    renderWithApp(
      <RecommendationsView />,
      studentSession({
        "GET /me/recommendations": () =>
          json([
            recommendation(
              rated
                ? {
                    feedback: {
                      rating: "helpful",
                      reason: null,
                      updated_at: "2026-10-10T08:00:00Z",
                    },
                  }
                : {},
            ),
          ]),
        "GET /me/recommendations/history": () => json([]),
        "GET /me/recommendations/preferences": () => json(preferences()),
        "PUT /me/recommendations/rec-1/feedback": ({ body }) => {
          calls.push(`PUT ${JSON.stringify(body)}`);
          rated = true;
          return json(recommendation());
        },
        "DELETE /me/recommendations/rec-1/feedback": () => {
          calls.push("DELETE");
          rated = false;
          return json(recommendation());
        },
      }),
    );
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Helpful" }));
    await waitFor(() => expect(calls).toEqual(['PUT {"rating":"helpful","reason":null}']));
    const pressed = await screen.findByRole("button", { name: "Helpful", pressed: true });
    await user.click(pressed);
    await waitFor(() => expect(calls.at(-1)).toBe("DELETE"));
  });

  it("loads older suggestions a page at a time when there are more", async () => {
    const offsets: string[] = [];
    const page = (start: number, size: number) =>
      Array.from({ length: size }, (_, i) =>
        recommendation({
          id: `old-${start + i}`,
          title: `Old idea ${start + i}`,
          rationale: "Earlier.",
          status: "completed",
        }),
      );
    renderWithApp(
      <RecommendationsView />,
      studentSession({
        "GET /me/recommendations": () => json([]),
        "GET /me/recommendations/history": ({ query }) => {
          const offset = Number(query.get("offset") ?? 0);
          offsets.push(String(offset));
          return json(offset === 0 ? page(0, 50) : page(50, 3));
        },
        "GET /me/recommendations/preferences": () => json(preferences()),
      }),
    );
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Show older suggestions" }));
    await waitFor(() => expect(offsets).toEqual(["0", "50"]));
    expect(await screen.findByText("Old idea 52")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Show older suggestions" }),
    ).not.toBeInTheDocument();
  });

  it("asks why when a suggestion was not helpful, and the reason is optional", async () => {
    const bodies: unknown[] = [];
    renderWithApp(
      <RecommendationsView />,
      studentSession({
        "GET /me/recommendations": () => json([recommendation()]),
        "GET /me/recommendations/history": () => json([]),
        "GET /me/recommendations/preferences": () => json(preferences()),
        "PUT /me/recommendations/rec-1/feedback": ({ body }) => {
          bodies.push(body);
          return json(recommendation({ status: "dismissed" }));
        },
      }),
    );
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Not helpful" }));
    expect(screen.getByText("What didn't work? (optional)")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Too long" }));
    await waitFor(() => expect(bodies).toEqual([{ rating: "not_helpful", reason: "too_long" }]));

    await user.click(await screen.findByRole("button", { name: "Not helpful" }));
    await user.click(screen.getByRole("button", { name: "Skip" }));
    await waitFor(() => expect(bodies.at(-1)).toEqual({ rating: "not_helpful", reason: null }));
  });

  it("points a counselling suggestion at booking", async () => {
    renderWithApp(
      <RecommendationsView />,
      studentSession({
        "GET /me/recommendations": () =>
          json([recommendation({ action: "book_counselling", title: "Talk it through" })]),
        "GET /me/recommendations/history": () => json([]),
        "GET /me/recommendations/preferences": () => json(preferences()),
      }),
    );
    const link = await screen.findByRole("link", { name: "Book a counselling session" });
    expect(link).toHaveAttribute("href", "/student/therapists");
  });

  it("saves what suits the student", async () => {
    const patches: unknown[] = [];
    renderWithApp(
      <RecommendationsView />,
      studentSession({
        "GET /me/recommendations": () => json([]),
        "GET /me/recommendations/history": () => json([]),
        "GET /me/recommendations/preferences": () => json(preferences()),
        "PATCH /me/recommendations/preferences": ({ body }) => {
          patches.push(body);
          return json(preferences({ max_minutes: 10, use_indicators: false }));
        },
      }),
    );
    const user = userEvent.setup();
    await screen.findByRole("heading", { name: "What suits you" });
    await user.selectOptions(screen.getByLabelText("Longest you want a resource to take"), "10");
    await user.click(screen.getByRole("button", { name: "Video" }));
    await user.click(screen.getByLabelText("Use my wellness indicators to tune suggestions"));
    await user.click(screen.getByRole("button", { name: "Save preferences" }));
    await waitFor(() =>
      expect(patches).toEqual([
        {
          preferred_formats: ["video"],
          max_minutes: 10,
          muted_areas: [],
          use_indicators: false,
        },
      ]),
    );
  });

  it("looks for new suggestions on request", async () => {
    let refreshed = false;
    renderWithApp(
      <RecommendationsView />,
      studentSession({
        "GET /me/recommendations": () => json([]),
        "GET /me/recommendations/history": () => json([]),
        "GET /me/recommendations/preferences": () => json(preferences()),
        "POST /me/recommendations/refresh": () => {
          refreshed = true;
          return json([]);
        },
      }),
    );
    await userEvent.setup().click(await screen.findByRole("button", { name: /Look for new ones/ }));
    await waitFor(() => expect(refreshed).toBe(true));
    expect(screen.getByText("No suggestions right now")).toBeInTheDocument();
  });

  it("explains a failure", async () => {
    renderWithApp(
      <RecommendationsView />,
      studentSession({ "GET /me/recommendations": () => problem(503, "Down") }),
    );
    expect((await screen.findAllByRole("alert")).length).toBeGreaterThan(0);
  });
});

describe("resources", () => {
  const resources = [
    resource(),
    resource({
      id: "res-2",
      title: "Study planning guide",
      resource_type: "article",
      tags: ["exams"],
      summary: "Plan your revision.",
    }),
  ];

  it("lists and filters by search text and type", async () => {
    const { container } = renderWithApp(
      <ResourcesView />,
      studentSession({ "GET /resources": () => json(resources) }),
    );
    const user = userEvent.setup();
    expect(await screen.findByText("Box breathing in four steps")).toBeInTheDocument();
    await user.type(screen.getByLabelText("Search"), "revision");
    expect(screen.queryByText("Box breathing in four steps")).not.toBeInTheDocument();
    expect(screen.getByText("Study planning guide")).toBeInTheDocument();
    await user.clear(screen.getByLabelText("Search"));
    await user.selectOptions(screen.getByLabelText("Type"), "exercise");
    expect(screen.getByRole("status")).toHaveTextContent("1 resource shown");
    await expectNoA11yViolations(container);
  });

  it("opens a resource, and only links out to web addresses", async () => {
    renderWithApp(
      <ResourceDetailView id="res-1" />,
      studentSession({
        "GET /resources/res-1": () =>
          json({ ...resource({ url: "https://example.org/x" }), body: "Breathe in for four." }),
      }),
    );
    expect(await screen.findByText("Breathe in for four.")).toBeInTheDocument();
    const link = screen.getByRole("link", { name: /Open the full resource/ });
    expect(link).toHaveAttribute("rel", "noopener noreferrer");
    expect(within(link).getByText("(opens in a new tab)")).toBeInTheDocument();
  });

  it("does not render a link for an unsafe address", async () => {
    renderWithApp(
      <ResourceDetailView id="res-1" />,
      studentSession({
        "GET /resources/res-1": () =>
          json({ ...resource({ url: "javascript:alert(1)" }), body: null }),
      }),
    );
    await screen.findByRole("heading", { level: 1, name: "Box breathing in four steps" });
    expect(screen.queryByRole("link", { name: /Open the full resource/ })).not.toBeInTheDocument();
  });
});
