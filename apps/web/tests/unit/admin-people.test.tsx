import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";

import { AdminDashboardView } from "@/components/admin/dashboard-view";
import { PeopleView } from "@/components/admin/people-view";
import { VerificationView } from "@/components/admin/verification-view";

import { expectNoA11yViolations } from "../helpers/a11y";
import { json, problem, renderWithApp } from "../helpers/render";
import { navigation } from "../helpers/navigation";
import {
  DEPT,
  SELF,
  STUDENT,
  THERAPIST,
  adminSession,
  dashboard,
  department,
  review,
  student,
  teacher,
  therapist,
  user,
} from "../helpers/admin-data";

beforeEach(() => navigation.reset());

describe("admin dashboard", () => {
  it("shows counts, accounts by role and the privacy reminder", async () => {
    const session = adminSession({ "GET /admin/dashboard": () => json(dashboard()) });
    const { container } = renderWithApp(<AdminDashboardView />, session);
    expect(await screen.findByText("Therapists to verify")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /Welcome, Asha/ })).toBeInTheDocument();
    expect(screen.getByText("Active people")).toBeInTheDocument();
    expect(screen.getByText("136")).toBeInTheDocument();
    expect(screen.getByText("5 invited, not yet set up")).toBeInTheDocument();
    expect(screen.getByText("1 licence(s) expire within 30 days")).toBeInTheDocument();
    const table = screen.getByRole("table", { name: "Accounts by role and status" });
    expect(within(table).getByRole("rowheader", { name: "Student" })).toBeInTheDocument();
    expect(screen.getByText(/cannot read what students write/)).toBeInTheDocument();
    await expectNoA11yViolations(container);
  });

  it("explains a failure instead of showing empty numbers", async () => {
    const session = adminSession({
      "GET /admin/dashboard": () => problem(500, "Something went wrong."),
    });
    renderWithApp(<AdminDashboardView />, session);
    expect(await screen.findByText(/Something went wrong|couldn't/i)).toBeInTheDocument();
    expect(screen.queryByText("Active people")).not.toBeInTheDocument();
  });
});

describe("people", () => {
  const base = {
    "GET /admin/departments": () => json([department()]),
  };

  it("lists students and searches with a debounced query", async () => {
    const user_ = userEvent.setup();
    const session = adminSession({
      ...base,
      "GET /admin/students": () => json({ items: [student()], total: 1 }),
    });
    const { container } = renderWithApp(<PeopleView />, session);
    expect(await screen.findByText("Aarini Chaudhary")).toBeInTheDocument();
    expect(screen.getByText(/Computer Science · year 2 · S-1001/)).toBeInTheDocument();
    await expectNoA11yViolations(container);

    await user_.type(screen.getByLabelText("Search by name or email"), "aar");
    await waitFor(() =>
      expect(
        session.api.calls.some((c) => c.path === "/admin/students" && c.query.get("q") === "aar"),
      ).toBe(true),
    );
    // One request for the finished word, not one per key.
    const withQuery = session.api.calls.filter(
      (c) => c.path === "/admin/students" && c.query.has("q"),
    );
    expect(withQuery).toHaveLength(1);
  });

  it("switches role tabs and calls the matching endpoint", async () => {
    const user_ = userEvent.setup();
    const session = adminSession({
      ...base,
      "GET /admin/students": () => json({ items: [], total: 0 }),
      "GET /admin/teachers": () => json({ items: [teacher()], total: 1 }),
      "GET /admin/therapist-accounts": () => json({ items: [therapist()], total: 1 }),
      "GET /admin/users": () => json({ items: [user({ role: "administrator" })], total: 1 }),
    });
    renderWithApp(<PeopleView />, session);
    expect(await screen.findByText("No one matches")).toBeInTheDocument();
    await user_.click(screen.getByRole("button", { name: "Teachers" }));
    expect(await screen.findByText("Asha Verma")).toBeInTheDocument();
    await user_.click(screen.getByRole("button", { name: "Therapists" }));
    expect(await screen.findByText("Dr Meera Rao")).toBeInTheDocument();
    expect(screen.getByText(/Verified · 12 of 40 students/)).toBeInTheDocument();
    await user_.click(screen.getByRole("button", { name: "Administrators" }));
    await screen.findByText("Aarini Chaudhary");
    const users = session.api.calls.filter((c) => c.path === "/admin/users");
    expect(users[0]?.query.get("role")).toBe("administrator");
  });

  it("suspends someone only after a confirmation, and sends the new status", async () => {
    const user_ = userEvent.setup();
    const patches: unknown[] = [];
    const session = adminSession({
      ...base,
      "GET /admin/students": () => json({ items: [student()], total: 1 }),
      [`PATCH /admin/users/${STUDENT}`]: (call) => {
        patches.push(call.body);
        return json(user({ status: "suspended" }));
      },
    });
    renderWithApp(<PeopleView />, session);
    await screen.findByText("Aarini Chaudhary");
    await user_.click(screen.getByRole("button", { name: "Actions for Aarini Chaudhary" }));
    await user_.click(await screen.findByRole("menuitem", { name: "Suspend" }));
    const dialog = await screen.findByRole("alertdialog");
    expect(dialog).toHaveTextContent("Suspend Aarini Chaudhary?");
    expect(patches).toEqual([]);
    await user_.click(within(dialog).getByRole("button", { name: "Suspend" }));
    await waitFor(() => expect(patches).toEqual([{ status: "suspended" }]));
  });

  it("does not suspend when the confirmation is cancelled", async () => {
    const user_ = userEvent.setup();
    const session = adminSession({
      ...base,
      "GET /admin/students": () => json({ items: [student()], total: 1 }),
    });
    renderWithApp(<PeopleView />, session);
    await screen.findByText("Aarini Chaudhary");
    await user_.click(screen.getByRole("button", { name: "Actions for Aarini Chaudhary" }));
    await user_.click(await screen.findByRole("menuitem", { name: "Deactivate" }));
    const dialog = await screen.findByRole("alertdialog");
    await user_.click(within(dialog).getByRole("button", { name: /Cancel/ }));
    expect(session.api.calls.some((c) => c.method === "PATCH")).toBe(false);
  });

  it("reactivates a suspended account without asking for confirmation", async () => {
    const user_ = userEvent.setup();
    const patches: unknown[] = [];
    const session = adminSession({
      ...base,
      "GET /admin/students": () => json({ items: [student({ status: "suspended" })], total: 1 }),
      [`PATCH /admin/users/${STUDENT}`]: (call) => {
        patches.push(call.body);
        return json(user());
      },
    });
    renderWithApp(<PeopleView />, session);
    await screen.findByText("Aarini Chaudhary");
    await user_.click(screen.getByRole("button", { name: "Actions for Aarini Chaudhary" }));
    await user_.click(await screen.findByRole("menuitem", { name: "Reactivate" }));
    await waitFor(() => expect(patches).toEqual([{ status: "active" }]));
  });

  it("offers no actions on the administrator's own row", async () => {
    const session = adminSession({
      ...base,
      "GET /admin/users": () =>
        json({
          items: [user({ id: SELF, full_name: "Asha Verma", role: "administrator" })],
          total: 1,
        }),
      "GET /admin/students": () => json({ items: [], total: 0 }),
    });
    const user_ = userEvent.setup();
    renderWithApp(<PeopleView />, session);
    await screen.findByText("No one matches");
    await user_.click(screen.getByRole("button", { name: "Administrators" }));
    expect(await screen.findByText("This is you")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Actions for/ })).not.toBeInTheDocument();
  });

  it("shows the server's explanation when an action is refused", async () => {
    const user_ = userEvent.setup();
    const session = adminSession({
      ...base,
      "GET /admin/students": () => json({ items: [student()], total: 1 }),
      [`POST /admin/users/${STUDENT}/sign-out`]: () => problem(403, "You cannot do that."),
    });
    renderWithApp(<PeopleView />, session);
    await screen.findByText("Aarini Chaudhary");
    await user_.click(screen.getByRole("button", { name: "Actions for Aarini Chaudhary" }));
    await user_.click(await screen.findByRole("menuitem", { name: "Sign out everywhere" }));
    expect(await screen.findByText("That didn't work")).toBeInTheDocument();
  });

  it("resends an invitation to someone who has not set up yet", async () => {
    const user_ = userEvent.setup();
    let sent = 0;
    const session = adminSession({
      ...base,
      "GET /admin/students": () => json({ items: [student({ status: "invited" })], total: 1 }),
      [`POST /admin/users/${STUDENT}/resend-invite`]: () => {
        sent += 1;
        return new Response(null, { status: 204 });
      },
    });
    renderWithApp(<PeopleView />, session);
    await screen.findByText("Aarini Chaudhary");
    await user_.click(screen.getByRole("button", { name: "Actions for Aarini Chaudhary" }));
    await user_.click(await screen.findByRole("menuitem", { name: "Send the invitation again" }));
    await waitFor(() => expect(sent).toBe(1));
  });

  it("validates the invitation before sending, then sends the typed payload", async () => {
    const user_ = userEvent.setup();
    const posts: unknown[] = [];
    const session = adminSession({
      ...base,
      "GET /admin/students": () => json({ items: [], total: 0 }),
      "POST /admin/users": (call) => {
        posts.push(call.body);
        return json(user(), 201);
      },
    });
    renderWithApp(<PeopleView />, session);
    await screen.findByText("No one matches");
    await user_.click(screen.getByRole("button", { name: "Invite someone" }));
    const dialog = await screen.findByRole("dialog", { name: "Invite someone" });
    await user_.click(await within(dialog).findByRole("button", { name: "Send invitation" }));
    expect(within(dialog).getByText("Enter their full name.")).toBeInTheDocument();
    expect(within(dialog).getByText("Enter a valid email address.")).toBeInTheDocument();
    expect(within(dialog).getByText("Choose a department.")).toBeInTheDocument();
    expect(posts).toEqual([]);

    await user_.type(within(dialog).getByLabelText("Full name"), "Ishaan Rao");
    await user_.type(within(dialog).getByLabelText("Email"), "ishaan@college.example");
    await user_.selectOptions(within(dialog).getByLabelText("Department"), DEPT);
    await user_.type(within(dialog).getByLabelText("Student number"), "S-2002");
    await user_.click(within(dialog).getByRole("button", { name: "Send invitation" }));
    await waitFor(() => expect(posts).toHaveLength(1));
    expect(posts[0]).toMatchObject({
      email: "ishaan@college.example",
      full_name: "Ishaan Rao",
      role: "student",
      department_code: "CS",
      student_number: "S-2002",
    });
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });

  it("asks for a licence number when inviting a therapist, not a department", async () => {
    const user_ = userEvent.setup();
    const session = adminSession({
      ...base,
      "GET /admin/students": () => json({ items: [], total: 0 }),
    });
    renderWithApp(<PeopleView />, session);
    await screen.findByText("No one matches");
    await user_.click(screen.getByRole("button", { name: "Invite someone" }));
    const dialog = await screen.findByRole("dialog", { name: "Invite someone" });
    await user_.selectOptions(await within(dialog).findByLabelText("Role"), "therapist");
    expect(within(dialog).getByLabelText("Licence number")).toBeInTheDocument();
    expect(within(dialog).queryByLabelText("Department")).not.toBeInTheDocument();
    expect(
      within(dialog).getByText("They cannot see students until you verify this."),
    ).toBeInTheDocument();
  });

  it("edits a student's details", async () => {
    const user_ = userEvent.setup();
    const patches: unknown[] = [];
    const session = adminSession({
      ...base,
      "GET /admin/students": () => json({ items: [student()], total: 1 }),
      [`PATCH /admin/students/${STUDENT}`]: (call) => {
        patches.push(call.body);
        return json(student({ year_of_study: 3 }));
      },
    });
    renderWithApp(<PeopleView />, session);
    await screen.findByText("Aarini Chaudhary");
    await user_.click(screen.getByRole("button", { name: "Actions for Aarini Chaudhary" }));
    await user_.click(await screen.findByRole("menuitem", { name: "Edit details" }));
    const dialog = await screen.findByRole("dialog", { name: "Edit Aarini Chaudhary" });
    const year = await within(dialog).findByLabelText("Year of study");
    await user_.clear(year);
    await user_.type(year, "3");
    await user_.click(within(dialog).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(patches).toHaveLength(1));
    expect(patches[0]).toMatchObject({ year_of_study: 3, department_id: DEPT });
  });
});

describe("therapist verification", () => {
  it("lists the waiting therapists and nothing about their students", async () => {
    const session = adminSession({
      "GET /admin/therapists": () => json([review()]),
    });
    const { container } = renderWithApp(<VerificationView />, session);
    expect(await screen.findByText(/Licence L-2200/)).toBeInTheDocument();
    expect(screen.getByText(/Licence L-2200/)).toBeInTheDocument();
    expect(session.api.calls[0]?.query.get("status")).toBe("pending");
    expect(screen.queryByText(/caseload/i)).not.toBeInTheDocument();
    await expectNoA11yViolations(container);
  });

  it("verifies a therapist with a new expiry date", async () => {
    const user_ = userEvent.setup();
    const patches: unknown[] = [];
    const session = adminSession({
      "GET /admin/therapists": () => json([review()]),
      [`PATCH /admin/therapists/${THERAPIST}/verification`]: (call) => {
        patches.push(call.body);
        return json(review({ verification_status: "verified" }));
      },
    });
    renderWithApp(<VerificationView />, session);
    await user_.click(await screen.findByRole("button", { name: /Review/ }));
    const dialog = await screen.findByRole("dialog", { name: "Review Dr Meera Rao" });
    const expires = within(dialog).getByLabelText("Licence expiry date");
    await user_.clear(expires);
    await user_.type(expires, "2028-01-31");
    await user_.click(within(dialog).getByRole("button", { name: "Save decision" }));
    await waitFor(() => expect(patches).toHaveLength(1));
    expect(patches[0]).toEqual({ status: "verified", licence_expires_on: "2028-01-31" });
  });

  it("requires a reason before refusing a registration", async () => {
    const user_ = userEvent.setup();
    const patches: unknown[] = [];
    const session = adminSession({
      "GET /admin/therapists": () => json([review()]),
      [`PATCH /admin/therapists/${THERAPIST}/verification`]: (call) => {
        patches.push(call.body);
        return json(review({ verification_status: "rejected" }));
      },
    });
    renderWithApp(<VerificationView />, session);
    await user_.click(await screen.findByRole("button", { name: /Review/ }));
    const dialog = await screen.findByRole("dialog");
    await user_.click(within(dialog).getByRole("button", { name: "Do not accept" }));
    await user_.click(within(dialog).getByRole("button", { name: "Save decision" }));
    expect(
      within(dialog).getByText("Say briefly why, so the therapist knows what to fix."),
    ).toBeInTheDocument();
    expect(patches).toEqual([]);
    await user_.type(within(dialog).getByLabelText("Reason"), "Licence not found.");
    await user_.click(within(dialog).getByRole("button", { name: "Save decision" }));
    await waitFor(() =>
      expect(patches).toEqual([{ status: "rejected", note: "Licence not found." }]),
    );
  });

  it("explains an empty queue", async () => {
    const session = adminSession({ "GET /admin/therapists": () => json([]) });
    renderWithApp(<VerificationView />, session);
    expect(await screen.findByText("Every therapist has been reviewed.")).toBeInTheDocument();
  });

  it("filters by decision", async () => {
    const user_ = userEvent.setup();
    const session = adminSession({
      "GET /admin/therapists": (call) =>
        json(
          call.query.get("status") === "verified"
            ? [review({ verification_status: "verified" })]
            : [],
        ),
    });
    renderWithApp(<VerificationView />, session);
    await screen.findByText("Every therapist has been reviewed.");
    await user_.click(screen.getByRole("button", { name: "Verified" }));
    expect(await screen.findByRole("button", { name: /Change/ })).toBeInTheDocument();
  });
});
