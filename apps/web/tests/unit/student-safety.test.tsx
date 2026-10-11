import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { CheckInView } from "@/components/student/check-in-view";
import { DashboardView } from "@/components/student/dashboard-view";
import { ConversationView } from "@/components/student/messages-views";
import { RecommendationsView } from "@/components/student/recommendations-view";
import { SafetyPanel, escalationText } from "@/components/student/safety-panel";
import type { CheckInResult } from "@/lib/api/student-schemas";

import { expectNoA11yViolations } from "../helpers/a11y";
import { json, problem, renderWithApp } from "../helpers/render";
import {
  THERAPIST_ID,
  conversation,
  dashboard,
  message,
  recommendation,
  safety,
  studentSession,
} from "../helpers/student-data";

const FORBIDDEN = /diagnos(is|ed)|disorder|depression|medication|dosage|you are (ill|sick)/i;

const immediate = () =>
  safety({
    level: "immediate",
    emergency_first: true,
    guidance: {
      title: "Please get help right now",
      message: "Your safety matters most right now.",
      steps: ["Call your local emergency number now.", "Stay with someone you trust."],
    },
    escalation: { status: "requested", basis: "vital_interest", care_team_notified: false },
  });

const moderate = () =>
  safety({
    level: "moderate",
    offer_outreach: true,
    escalation: { status: "not_requested", basis: "not_needed", care_team_notified: false },
    recommendations_paused: false,
    paused_until: null,
  });

const supportRequest = (already_open = false) =>
  json(
    {
      id: "r1",
      status: "open",
      already_open,
      reaches_care_team: true,
      created_at: "2026-10-10T08:00:00Z",
    },
    201,
  );

describe("safety panel", () => {
  it("leads with the emergency number at immediate risk and interrupts as an alert", async () => {
    const { container } = renderWithApp(<SafetyPanel safety={immediate()} />, studentSession());
    const panel = screen.getByRole("alert", { name: "Please get help right now" });
    expect(within(panel).getByText("If you're in danger right now")).toBeInTheDocument();
    expect(within(panel).getByText(/Call your local emergency number now, or go to/)).toBeVisible();
    const steps = within(panel).getAllByRole("listitem");
    expect(steps[0]).toHaveTextContent("Call your local emergency number now.");
    expect(within(panel).getByText(/counselling team has been asked to reach out/)).toBeVisible();
    expect(within(panel).getByText(/won't see what you wrote/)).toBeVisible();
    await expectNoA11yViolations(container);
  });

  it("lists the configured contacts and links to the counsellor and emergency page", () => {
    renderWithApp(<SafetyPanel safety={safety()} />, studentSession());
    const contacts = screen.getByRole("list", { name: "Support contacts" });
    expect(within(contacts).getByText("Local emergency services")).toBeInTheDocument();
    expect(within(contacts).getByText("Demo helpline")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Message your counsellor" })).toHaveAttribute(
      "href",
      "/student/messages",
    );
    expect(screen.getByRole("link", { name: "Book a counsellor" })).toHaveAttribute(
      "href",
      "/student/therapists",
    );
    expect(screen.getByRole("link", { name: "Get help now" })).toHaveAttribute(
      "href",
      "/student/emergency",
    );
  });

  it("hides the message link when the student has no care team yet", () => {
    renderWithApp(
      <SafetyPanel
        safety={safety({
          counselling: {
            has_care_team: false,
            message_path: null,
            booking_path: "/student/therapists",
          },
        })}
      />,
      studentSession(),
    );
    expect(screen.queryByRole("link", { name: "Message your counsellor" })).toBeNull();
    expect(screen.getByRole("link", { name: "Book a counsellor" })).toBeInTheDocument();
  });

  it("always shows the disclaimer that it is not an emergency service", () => {
    for (const s of [immediate(), safety(), moderate()]) {
      const { unmount } = renderWithApp(<SafetyPanel safety={s} />, studentSession());
      expect(screen.getByRole("note")).toHaveTextContent("not an emergency service");
      unmount();
    }
  });

  it("says suggestions are paused only when they are", () => {
    const { unmount } = renderWithApp(<SafetyPanel safety={safety()} />, studentSession());
    expect(screen.getByText(/paused your usual suggestions/)).toBeInTheDocument();
    unmount();
    renderWithApp(<SafetyPanel safety={moderate()} />, studentSession());
    expect(screen.queryByText(/paused your usual suggestions/)).toBeNull();
  });

  it("is a calm status, not an alert, for a moderate concern", () => {
    renderWithApp(<SafetyPanel safety={moderate()} />, studentSession());
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.getByRole("status")).toBeInTheDocument();
    expect(screen.queryByText("If you're in danger right now")).toBeNull();
  });

  it("tells a student without consent that nobody was told, and lets them ask with one tap", async () => {
    const session = studentSession({ "POST /me/support-requests": () => supportRequest() });
    renderWithApp(
      <SafetyPanel
        safety={safety({
          offer_outreach: true,
          escalation: { status: "not_requested", basis: "no_consent", care_team_notified: false },
        })}
      />,
      session,
    );
    expect(screen.getByText(/Nobody has been told about what you wrote/)).toBeInTheDocument();
    await userEvent.setup().click(screen.getByRole("button", { name: "Ask someone to reach out" }));
    expect(await screen.findByText("Your request is in")).toBeInTheDocument();
    const post = session.api.calls.find((c) => c.path === "/me/support-requests");
    expect(post?.method).toBe("POST");
    // The note itself is never forwarded with the request.
    expect(post?.body).toEqual({});
  });

  it("does not claim a new request was sent when one is already open", async () => {
    renderWithApp(
      <SafetyPanel safety={moderate()} />,
      studentSession({ "POST /me/support-requests": () => supportRequest(true) }),
    );
    await userEvent.setup().click(screen.getByRole("button", { name: "Ask someone to reach out" }));
    expect(await screen.findByText(/already have a request open/)).toBeInTheDocument();
  });

  it("points to the contacts when asking for outreach fails", async () => {
    renderWithApp(
      <SafetyPanel safety={moderate()} />,
      studentSession({ "POST /me/support-requests": () => problem(503, "Unavailable") }),
    );
    await userEvent.setup().click(screen.getByRole("button", { name: "Ask someone to reach out" }));
    expect(await screen.findByText(/use one of the contacts above/)).toBeInTheDocument();
  });

  it("never says someone was told when escalation failed", () => {
    renderWithApp(
      <SafetyPanel
        safety={safety({
          offer_outreach: true,
          escalation: { status: "failed", basis: "consent", care_team_notified: false },
        })}
      />,
      studentSession(),
    );
    expect(screen.getByText(/couldn't reach the counselling team/)).toBeInTheDocument();
    expect(screen.queryByText(/has been asked to reach out/)).toBeNull();
    expect(screen.getByRole("button", { name: "Ask someone to reach out" })).toBeInTheDocument();
  });

  it("words every escalation outcome without diagnosing or claiming to share the text", () => {
    const outcomes: Array<Parameters<typeof escalationText>[0]["escalation"]> = [
      { status: "requested", basis: "consent", care_team_notified: true },
      { status: "requested", basis: "vital_interest", care_team_notified: false },
      { status: "already_open", basis: "companion_notice", care_team_notified: true },
      { status: "failed", basis: "consent", care_team_notified: false },
      { status: "not_requested", basis: "no_consent", care_team_notified: false },
    ];
    for (const escalation of outcomes) {
      const text = escalationText(safety({ escalation }));
      expect(text).toBeTruthy();
      expect(text).not.toMatch(FORBIDDEN);
      expect(text).not.toMatch(/(can|will) (see|read) what you wrote/);
    }
    expect(escalationText(moderate())).toBeNull();
  });
});

describe("safety in the student's flows", () => {
  const checkIn = (extra: Partial<CheckInResult> = {}): CheckInResult => ({
    mood: {
      id: "e1",
      mood_score: 1,
      energy_level: null,
      emotions: [],
      note: null,
      logged_at: "2026-10-10T08:00:00Z",
    },
    stress: null,
    sleep: null,
    support: { message: "That sounds really hard.", help_path: "/student/emergency" },
    ...extra,
  });

  it("replaces the gentle callout with the safety panel after a concerning check-in", async () => {
    renderWithApp(
      <CheckInView />,
      studentSession({ "POST /me/check-ins": () => json(checkIn({ safety: immediate() }), 201) }),
    );
    const user = userEvent.setup();
    await screen.findByRole("heading", { level: 1 });
    await user.click(
      within(screen.getByRole("group", { name: "Mood" })).getByRole("radio", { name: /Very low/ }),
    );
    await user.click(screen.getByRole("button", { name: "Save check-in" }));
    expect(await screen.findByRole("alert", { name: "Please get help right now" })).toBeVisible();
    expect(screen.queryByText("That sounds really hard.")).toBeNull();
  });

  it("shows the panel after a student's message to their counsellor raises a concern", async () => {
    renderWithApp(
      <ConversationView otherId={THERAPIST_ID} />,
      studentSession({
        "GET /me/conversations": () => json([conversation()]),
        [`GET /me/conversations/${THERAPIST_ID}/messages`]: () => json([message({ id: "m1" })]),
        [`POST /me/conversations/${THERAPIST_ID}/read`]: () => json({ marked_read: 0 }),
        [`POST /me/conversations/${THERAPIST_ID}/messages`]: () =>
          json(
            {
              message: message({ id: "m2", mine: true }),
              support: null,
              safety: safety({
                escalation: {
                  status: "requested",
                  basis: "care_team_message",
                  care_team_notified: true,
                },
              }),
            },
            201,
          ),
      }),
    );
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText("Write a message"), "synthetic test message");
    await user.click(screen.getByRole("button", { name: "Send" }));
    const panel = await screen.findByRole("alert", {
      name: "You don't have to go through this alone",
    });
    expect(within(panel).getByText(/Your counsellor has been asked to reach out/)).toBeVisible();
  });

  it("pauses suggestions and puts support first while a concern is open", async () => {
    const { container } = renderWithApp(
      <RecommendationsView />,
      studentSession({
        "GET /me/recommendations": () => json([]),
        "GET /me/recommendations/history": () => json([]),
        "GET /me/recommendations/preferences": () =>
          json({
            preferred_formats: [],
            max_minutes: null,
            muted_areas: [],
            use_indicators: true,
            available_formats: ["article"],
            available_areas: ["counselling"],
          }),
        "GET /me/safety/status": () =>
          json({
            recommendations_paused: true,
            support: safety(),
            disclaimer: "MindMitra is not an emergency service.",
          }),
      }),
    );
    expect(await screen.findByText("Suggestions are paused for now")).toBeInTheDocument();
    expect(
      screen.getByRole("alert", { name: "You don't have to go through this alone" }),
    ).toBeInTheDocument();
    await expectNoA11yViolations(container);
  });

  it("keeps the usual suggestions when nothing is paused", async () => {
    renderWithApp(
      <RecommendationsView />,
      studentSession({
        "GET /me/recommendations": () => json([recommendation()]),
        "GET /me/recommendations/history": () => json([]),
        "GET /me/recommendations/preferences": () =>
          json({
            preferred_formats: [],
            max_minutes: null,
            muted_areas: [],
            use_indicators: true,
            available_formats: ["article"],
            available_areas: ["counselling"],
          }),
        "GET /me/safety/status": () =>
          json({
            recommendations_paused: false,
            support: null,
            disclaimer: "MindMitra is not an emergency service.",
          }),
      }),
    );
    expect(await screen.findByText("Try a short breathing exercise")).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByRole("alert")).toBeNull());
  });

  it("puts support at the top of the dashboard while suggestions are paused", async () => {
    renderWithApp(
      <DashboardView />,
      studentSession({ "GET /me/dashboard": () => json(dashboard({ safety: safety() })) }),
    );
    expect(
      await screen.findByRole("alert", { name: "You don't have to go through this alone" }),
    ).toBeInTheDocument();
    expect(screen.getByText(/Suggestions are paused for now/)).toBeInTheDocument();
  });

  it("shows no safety panel on an ordinary dashboard", async () => {
    renderWithApp(
      <DashboardView />,
      studentSession({ "GET /me/dashboard": () => json(dashboard()) }),
    );
    await screen.findByRole("heading", { level: 1 });
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.queryByText(/Suggestions are paused/)).toBeNull();
  });
});
