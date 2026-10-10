import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import {
  AppointmentsView,
  TherapistProfileView,
  TherapistSearchView,
} from "@/components/student/care-views";

import { expectNoA11yViolations } from "../helpers/a11y";
import { json, problem, renderWithApp } from "../helpers/render";
import {
  SLOT_ID,
  THERAPIST_ID,
  appointment,
  slot,
  studentSession,
  therapist,
} from "../helpers/student-data";

const full = therapist({
  id: "0192a000-0000-7000-8000-000000000002",
  full_name: "Dr. Full Calendar",
  accepting_new_students: false,
  specialties: ["Grief"],
  languages: ["English"],
});

describe("therapist search", () => {
  const handlers = {
    "GET /therapists": () =>
      json([
        therapist(),
        full,
        therapist({
          id: "0192a000-0000-7000-8000-000000000003",
          full_name: "Dr. Arun Rao",
          specialties: ["Sleep"],
          languages: ["Tamil"],
        }),
      ]),
  };

  it("lists therapists taking new students first, and filters by focus and language", async () => {
    const { container } = renderWithApp(<TherapistSearchView />, studentSession(handlers));
    const user = userEvent.setup();
    expect(await screen.findByText("Dr. Priya Nair")).toBeInTheDocument();
    expect(screen.queryByText("Dr. Full Calendar")).not.toBeInTheDocument(); // not accepting
    expect(screen.getByRole("status")).toHaveTextContent("2 therapists shown");

    await user.selectOptions(screen.getByLabelText("Focus area"), "Sleep");
    expect(screen.queryByText("Dr. Priya Nair")).not.toBeInTheDocument();
    expect(screen.getByText("Dr. Arun Rao")).toBeInTheDocument();

    await user.selectOptions(screen.getByLabelText("Focus area"), "");
    await user.selectOptions(screen.getByLabelText("Language"), "Hindi");
    expect(screen.getByText("Dr. Priya Nair")).toBeInTheDocument();
    expect(screen.queryByText("Dr. Arun Rao")).not.toBeInTheDocument();
    await expectNoA11yViolations(container);
  });

  it("can include therapists who are full, and searches by name", async () => {
    renderWithApp(<TherapistSearchView />, studentSession(handlers));
    const user = userEvent.setup();
    await screen.findByText("Dr. Priya Nair");
    await user.click(screen.getByLabelText(/Only show therapists taking new students/));
    expect(screen.getByText("Dr. Full Calendar")).toBeInTheDocument();
    expect(screen.getByText("Not taking new students")).toBeInTheDocument();
    await user.type(screen.getByLabelText("Name"), "arun");
    expect(screen.getByRole("status")).toHaveTextContent("1 therapist shown");
  });

  it("points to urgent support when nobody matches", async () => {
    renderWithApp(<TherapistSearchView />, studentSession({ "GET /therapists": () => json([]) }));
    expect(await screen.findByText("No one matches yet")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Urgent support" })).toHaveAttribute(
      "href",
      "/student/emergency",
    );
  });
});

describe("therapist profile and booking", () => {
  const profile = {
    ...therapist(),
    bio: "I work with students on exam anxiety.",
  };

  function setup(extra: Parameters<typeof studentSession>[0] = {}) {
    const session = studentSession({
      [`GET /therapists/${THERAPIST_ID}`]: () => json(profile),
      [`GET /therapists/${THERAPIST_ID}/slots`]: () => json([slot()]),
      ...extra,
    });
    renderWithApp(<TherapistProfileView id={THERAPIST_ID} />, session);
    return session;
  }

  it("shows the profile and open times", async () => {
    setup();
    expect(await screen.findByRole("heading", { level: 1, name: "Dr. Priya Nair" })).toBeVisible();
    expect(screen.getByText("I work with students on exam anxiety.")).toBeInTheDocument();
    expect(await screen.findByRole("button", { name: /Video call/ })).toBeInTheDocument();
  });

  it("requests the chosen time with an optional private reason", async () => {
    const session = setup({
      "POST /me/appointments": () => json(appointment({ status: "requested" }), 201),
    });
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: /Video call/ }));
    const dialog = await screen.findByRole("dialog", { name: "Request this appointment" });
    await user.type(within(dialog).getByLabelText(/What would you like to talk about/), "Exams");
    await user.click(within(dialog).getByRole("button", { name: "Send request" }));

    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    const post = session.api.calls.find(
      (c) => c.method === "POST" && c.path === "/me/appointments",
    )!;
    expect(post.body).toEqual({ availability_id: SLOT_ID, reason: "Exams" });
    expect(await screen.findByRole("link", { name: "See your appointments" })).toBeInTheDocument();
  });

  it("works without a reason", async () => {
    const session = setup({
      "POST /me/appointments": () => json(appointment({ status: "requested" }), 201),
    });
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: /Video call/ }));
    await user.click(await screen.findByRole("button", { name: "Send request" }));
    await waitFor(() =>
      expect(
        session.api.calls.find((c) => c.path === "/me/appointments" && c.method === "POST")?.body,
      ).toEqual({ availability_id: SLOT_ID }),
    );
  });

  it("explains why a booking failed and keeps the dialog open", async () => {
    setup({
      "POST /me/appointments": () =>
        problem(
          409,
          "You already have 3 upcoming appointments. Cancel one before booking another.",
        ),
    });
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: /Video call/ }));
    await user.click(await screen.findByRole("button", { name: "Send request" }));
    expect(await screen.findByText(/already have 3 upcoming/)).toBeInTheDocument();
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });

  it("offers messaging only for a therapist on the student's care team", async () => {
    setup({
      [`GET /therapists/${THERAPIST_ID}`]: () => json({ ...profile, on_my_care_team: true }),
    });
    expect(await screen.findByRole("link", { name: /Message/ })).toHaveAttribute(
      "href",
      `/student/messages/${THERAPIST_ID}`,
    );
  });

  it("says so when there are no open times", async () => {
    setup({ [`GET /therapists/${THERAPIST_ID}/slots`]: () => json([]) });
    expect(await screen.findByText("No openings right now")).toBeInTheDocument();
  });

  it("shows a calm error for a therapist who can't be found", async () => {
    renderWithApp(
      <TherapistProfileView id={THERAPIST_ID} />,
      studentSession({
        [`GET /therapists/${THERAPIST_ID}`]: () => problem(404, "Not found"),
        [`GET /therapists/${THERAPIST_ID}/slots`]: () => problem(404, "Not found"),
      }),
    );
    expect(await screen.findByRole("alert")).toBeInTheDocument();
  });
});

describe("appointment history", () => {
  const upcoming = appointment({ id: "a-up", status: "requested", reason: "Exam stress" });
  const past = appointment({
    id: "a-past",
    status: "completed",
    starts_at: "2026-09-01T10:00:00Z",
    ends_at: "2026-09-01T10:50:00Z",
    can_cancel: false,
  });
  const cancelled = appointment({ id: "a-can", status: "cancelled", can_cancel: false });

  it("separates upcoming appointments from history and labels each status in words", async () => {
    const { container } = renderWithApp(
      <AppointmentsView />,
      studentSession({
        "GET /me/appointments": ({ query }) =>
          json(query.get("upcoming") === "true" ? [upcoming] : [upcoming, past, cancelled]),
      }),
    );
    const section = (name: string) =>
      screen.getByRole("heading", { name }).closest("[data-slot=card]") as HTMLElement;
    expect(await screen.findByText("Waiting for confirmation")).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.getByRole("heading", { name: "History" })).toBeInTheDocument(),
    );
    expect(
      within(section("Upcoming")).getByText("Exam stress", { exact: false }),
    ).toBeInTheDocument();
    expect(within(section("History")).getByText("Completed")).toBeInTheDocument();
    expect(within(section("History")).getByText("Cancelled")).toBeInTheDocument();
    expect(
      within(section("History")).queryByText("Waiting for confirmation"),
    ).not.toBeInTheDocument();
    await expectNoA11yViolations(container);
  });

  it("asks before cancelling, then cancels and refreshes", async () => {
    let cancelledNow = false;
    const session = studentSession({
      "GET /me/appointments": ({ query }) => {
        const list = cancelledNow ? [] : [upcoming];
        return json(query.get("upcoming") === "true" ? list : [...list, past]);
      },
      "PATCH /me/appointments/a-up": () => {
        cancelledNow = true;
        return json({ ...upcoming, status: "cancelled", can_cancel: false });
      },
    });
    renderWithApp(<AppointmentsView />, session);
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Cancel" }));
    const dialog = await screen.findByRole("alertdialog");
    expect(dialog).toHaveTextContent("Dr. Priya Nair");

    await user.click(within(dialog).getByRole("button", { name: "Keep it" }));
    expect(session.api.calls.some((c) => c.method === "PATCH")).toBe(false);

    await user.click(screen.getByRole("button", { name: "Cancel" }));
    await user.click(
      within(await screen.findByRole("alertdialog")).getByRole("button", {
        name: "Cancel appointment",
      }),
    );
    await waitFor(() =>
      expect(session.api.calls.find((c) => c.method === "PATCH")?.body).toEqual({
        status: "cancelled",
      }),
    );
    expect(await screen.findByText("Nothing booked")).toBeInTheDocument();
  });

  it("hides the cancel button when the API says it is too late", async () => {
    renderWithApp(
      <AppointmentsView />,
      studentSession({
        "GET /me/appointments": () => json([appointment({ can_cancel: false })]),
      }),
    );
    await screen.findByText("Confirmed");
    expect(screen.queryByRole("button", { name: "Cancel" })).not.toBeInTheDocument();
  });
});
