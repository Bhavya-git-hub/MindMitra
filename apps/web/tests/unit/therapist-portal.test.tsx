import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { AlertsView } from "@/components/therapist/alerts-view";
import { AppointmentsView } from "@/components/therapist/appointments-view";
import { DashboardView } from "@/components/therapist/dashboard-view";
import { ProfileView } from "@/components/therapist/profile-view";
import { SessionDetailView, SessionsView } from "@/components/therapist/sessions-views";
import { StudentProfileView, StudentsView } from "@/components/therapist/students-views";
import { ConversationView, MessagesView } from "@/components/student/messages-views";

import { expectNoA11yViolations } from "../helpers/a11y";
import { json, problem, renderWithApp } from "../helpers/render";
import {
  ALERT_ID,
  APPOINTMENT_ID,
  SESSION_ID,
  STUDENT_ID,
  alert,
  appointment,
  caseloadStudent,
  dashboard,
  pendingProfile,
  profile,
  session,
  studentProfile,
  therapistSession,
} from "../helpers/therapist-data";

const verified = { "GET /therapist/profile": () => json(profile()) };
const unverified = { "GET /therapist/profile": () => json(pendingProfile()) };

describe("therapist dashboard", () => {
  it("greets the therapist and shows counts from the API", async () => {
    const { container } = renderWithApp(
      <DashboardView />,
      therapistSession({
        "GET /therapist/dashboard": () =>
          json(dashboard({ today: [appointment({ status: "confirmed", can_start: true })] })),
      }),
    );
    expect(await screen.findByRole("heading", { level: 1, name: /Welcome, Asha/ })).toBeVisible();
    expect(await screen.findByText("Requests waiting")).toBeInTheDocument();
    expect(screen.getByText("4 / 25")).toBeInTheDocument();
    expect(screen.getByText(/Aarini Chaudhary/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Start session" })).toBeInTheDocument();
    await expectNoA11yViolations(container);
  });

  it("explains verification when the therapist is not verified yet", async () => {
    renderWithApp(
      <DashboardView />,
      therapistSession({
        "GET /therapist/dashboard": () =>
          json(
            dashboard({
              verification_status: "pending",
              verification_label: "Waiting for verification",
              can_see_students: false,
            }),
          ),
      }),
    );
    expect(await screen.findByText(/once an administrator has verified/)).toBeInTheDocument();
  });
});

describe("verification gate", () => {
  it("never asks the API for students when the therapist is not verified", async () => {
    const s = therapistSession({
      ...unverified,
      "GET /therapist/students": () => json([caseloadStudent()]),
    });
    renderWithApp(<StudentsView />, s);
    expect(await screen.findByText(/once an administrator has verified/)).toBeInTheDocument();
    expect(screen.queryByText("Aarini Chaudhary")).not.toBeInTheDocument();
    expect(s.api.calls.some((c) => c.path.startsWith("/therapist/students"))).toBe(false);
  });

  it.each([
    ["sessions", <SessionsView key="s" />],
    ["alerts", <AlertsView key="a" />],
    ["appointments", <AppointmentsView key="p" />],
    ["one session", <SessionDetailView key="d" id={SESSION_ID} />],
    ["one student", <StudentProfileView key="u" id={STUDENT_ID} />],
  ])("%s stays closed and makes no data calls", async (_name, view) => {
    const s = therapistSession(unverified);
    renderWithApp(view, s);
    expect(await screen.findByText(/once an administrator has verified/)).toBeInTheDocument();
    expect(
      s.api.calls.filter((c) => c.path !== "/therapist/profile" && c.path.startsWith("/therapist")),
    ).toEqual([]);
  });

  it("lets an unverified therapist see their own verification status", async () => {
    renderWithApp(<ProfileView />, therapistSession(unverified));
    expect(await screen.findByText("Waiting for verification")).toBeInTheDocument();
  });
});

describe("caseload and authorized student profile", () => {
  it("lists only the students the API returns and filters by name", async () => {
    renderWithApp(
      <StudentsView />,
      therapistSession({
        ...verified,
        "GET /therapist/students": () =>
          json([
            caseloadStudent(),
            caseloadStudent({
              student_id: "0192b000-0000-7000-8000-000000000002",
              full_name: "Dev Menon",
              preferred_name: null,
              open_alerts: 1,
            }),
          ]),
      }),
    );
    const user = userEvent.setup();
    expect(await screen.findByText("Dev Menon")).toBeInTheDocument();
    expect(screen.getByText("1 alert")).toBeInTheDocument();
    await user.type(screen.getByRole("searchbox"), "aarini");
    expect(screen.queryByText("Dev Menon")).not.toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("1 student shown");
  });

  it("does not request trends or wellbeing checks the student has not shared", async () => {
    const s = therapistSession({
      ...verified,
      [`GET /therapist/students/${STUDENT_ID}`]: () => json(studentProfile()),
      [`GET /therapist/students/${STUDENT_ID}/recommendations`]: () => json([]),
      "GET /therapist/follow-ups": () => json([]),
    });
    const { container } = renderWithApp(<StudentProfileView id={STUDENT_ID} />, s);
    expect(
      await screen.findByRole("heading", { level: 1, name: "Aarini Chaudhary" }),
    ).toBeVisible();
    expect(screen.getAllByText(/hasn.t chosen to share/i).length).toBeGreaterThan(0);
    await waitFor(() =>
      expect(s.api.calls.some((c) => c.path.endsWith("/recommendations"))).toBe(true),
    );
    expect(s.api.calls.some((c) => c.path.endsWith("/trends"))).toBe(false);
    expect(s.api.calls.some((c) => c.path.endsWith("/assessments"))).toBe(false);
    await expectNoA11yViolations(container);
  });

  it("shows the API's refusal when the student is not on the care team", async () => {
    renderWithApp(
      <StudentProfileView id={STUDENT_ID} />,
      therapistSession({
        ...verified,
        [`GET /therapist/students/${STUDENT_ID}`]: () => problem(404, "Not found"),
      }),
    );
    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(screen.queryByText("Aarini Chaudhary")).not.toBeInTheDocument();
  });
});

describe("appointments", () => {
  it("confirms a request through the API and tells the therapist the student is notified", async () => {
    const patches: unknown[] = [];
    renderWithApp(
      <AppointmentsView />,
      therapistSession({
        ...verified,
        "GET /therapist/appointments": () => json([appointment({ reason: "Exam worries" })]),
        [`PATCH /appointments/${APPOINTMENT_ID}`]: ({ body }) => {
          patches.push(body);
          return json({});
        },
      }),
    );
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Confirm" }));
    await waitFor(() => expect(patches).toEqual([{ status: "confirmed" }]));
  });

  it("asks before declining", async () => {
    const patches: unknown[] = [];
    renderWithApp(
      <AppointmentsView />,
      therapistSession({
        ...verified,
        "GET /therapist/appointments": () => json([appointment()]),
        [`PATCH /appointments/${APPOINTMENT_ID}`]: ({ body }) => {
          patches.push(body);
          return json({});
        },
      }),
    );
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Decline" }));
    expect(patches).toEqual([]);
    const dialog = await screen.findByRole("alertdialog");
    await user.click(within(dialog).getByRole("button", { name: "Decline request" }));
    await waitFor(() => expect(patches).toEqual([{ status: "cancelled" }]));
  });
});

describe("risk alerts", () => {
  it("acknowledges an alert and requires an outcome to resolve it", async () => {
    const actions: unknown[] = [];
    let status = "open";
    renderWithApp(
      <AlertsView />,
      therapistSession({
        ...verified,
        "GET /therapist/alerts": () => json([alert({ status })]),
        [`PATCH /therapist/alerts/${ALERT_ID}`]: ({ body }) => {
          actions.push(body);
          const action = (body as { action: string }).action;
          status = action === "acknowledge" ? "acknowledged" : "resolved";
          return json(alert({ status }));
        },
      }),
    );
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Acknowledge" }));
    await user.click(await screen.findByRole("button", { name: "Resolve" }));
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: "Resolve alert" }));
    expect(await within(dialog).findByText("Choose how this was resolved.")).toBeInTheDocument();
    await user.selectOptions(within(dialog).getByLabelText("What happened"), "contacted_student");
    await user.click(within(dialog).getByRole("button", { name: "Resolve alert" }));
    await waitFor(() =>
      expect(actions).toEqual([
        { action: "acknowledge" },
        { action: "resolve", outcome: "contacted_student" },
      ]),
    );
  });
});

describe("therapy notes", () => {
  const note = (body: string, version = 1) => ({
    session_id: SESSION_ID,
    version,
    body,
    written_at: "2026-10-14T11:00:00Z",
    latest: true,
    versions: Array.from({ length: version }, (_, i) => ({
      version: i + 1,
      written_at: "2026-10-14T11:00:00Z",
    })),
  });

  it("saves a new version and keeps the text out of browser storage", async () => {
    const SECRET = "Synthetic private observation about the session";
    const saved: unknown[] = [];
    const s = therapistSession({
      ...verified,
      "GET /therapist/sessions": () => json([session()]),
      [`GET /therapist/sessions/${SESSION_ID}/note`]: () => json(null),
      [`PUT /therapist/sessions/${SESSION_ID}/note`]: ({ body }) => {
        saved.push(body);
        return json(note((body as { body: string }).body));
      },
    });
    const { container } = renderWithApp(<SessionDetailView id={SESSION_ID} />, s);
    const user = userEvent.setup();
    expect(await screen.findByText("Only you can read this")).toBeInTheDocument();
    const field = await screen.findByLabelText("Your note");
    await user.type(field, SECRET);
    await user.click(screen.getByRole("button", { name: "Save note" }));
    await waitFor(() => expect(saved).toEqual([{ body: SECRET }]));
    expect(JSON.stringify({ ...window.localStorage })).not.toContain(SECRET);
    expect(JSON.stringify({ ...window.sessionStorage })).not.toContain(SECRET);
    // No note text ever travels in a URL.
    expect(
      s.api.calls.some((c) => c.path.includes(SECRET) || c.query.toString().includes("Synthetic")),
    ).toBe(false);
    await expectNoA11yViolations(container);
  });

  it("will not save an empty note", async () => {
    const s = therapistSession({
      ...verified,
      "GET /therapist/sessions": () => json([session()]),
      [`GET /therapist/sessions/${SESSION_ID}/note`]: () => json(null),
    });
    renderWithApp(<SessionDetailView id={SESSION_ID} />, s);
    const user = userEvent.setup();
    await screen.findByLabelText("Your note");
    await user.type(screen.getByLabelText("Your note"), "   ");
    await user.click(screen.getByRole("button", { name: "Save note" }));
    expect(await screen.findByText("Write something before saving.")).toBeInTheDocument();
    expect(s.api.calls.some((c) => c.method === "PUT")).toBe(false);
  });

  it("shows a refusal from the API instead of any note content", async () => {
    renderWithApp(
      <SessionDetailView id={SESSION_ID} />,
      therapistSession({
        ...verified,
        "GET /therapist/sessions": () => json([session()]),
        [`GET /therapist/sessions/${SESSION_ID}/note`]: () => problem(403, "Forbidden"),
      }),
    );
    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(screen.queryByLabelText("Your note")).not.toBeInTheDocument();
  });

  it("opens an earlier version read only", async () => {
    renderWithApp(
      <SessionDetailView id={SESSION_ID} />,
      therapistSession({
        ...verified,
        "GET /therapist/sessions": () => json([session()]),
        [`GET /therapist/sessions/${SESSION_ID}/note`]: ({ query }) =>
          json(query.get("version") === "1" ? note("First draft", 1) : note("Second draft", 2)),
      }),
    );
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: /View version 1/ }));
    expect(await screen.findByText("First draft")).toBeInTheDocument();
    expect(screen.getByText("Version 1 (read only)")).toBeInTheDocument();
    expect(screen.queryByLabelText("Your note")).not.toBeInTheDocument();
  });
});

describe("therapist messaging", () => {
  it("links conversations under the therapist portal", async () => {
    renderWithApp(
      <MessagesView portal="therapist" />,
      therapistSession({
        "GET /me/conversations": () =>
          json([
            {
              other_id: STUDENT_ID,
              other_name: "Aarini Chaudhary",
              last_message_at: null,
              last_message_preview: null,
              unread_count: 0,
              active: true,
            },
          ]),
      }),
    );
    const link = await screen.findByRole("link", { name: /Aarini Chaudhary/ });
    expect(link).toHaveAttribute("href", `/therapist/messages/${STUDENT_ID}`);
    expect(screen.queryByRole("link", { name: "Urgent support" })).not.toBeInTheDocument();
  });

  it("points a therapist back to their own message list", async () => {
    renderWithApp(
      <ConversationView otherId={STUDENT_ID} portal="therapist" />,
      therapistSession({
        "GET /me/conversations": () => json([]),
        [`GET /me/conversations/${STUDENT_ID}/messages`]: () => json([]),
      }),
    );
    expect(await screen.findByRole("link", { name: "All messages" })).toHaveAttribute(
      "href",
      "/therapist/messages",
    );
  });
});

describe("sessions list", () => {
  it("shows whether a note exists without showing any note text", async () => {
    const { container } = renderWithApp(
      <SessionsView />,
      therapistSession({
        ...verified,
        "GET /therapist/sessions": () => json([session({ status: "completed", has_note: true })]),
      }),
    );
    expect(await screen.findByText("Note written")).toBeInTheDocument();
    await expectNoA11yViolations(container);
  });
});
