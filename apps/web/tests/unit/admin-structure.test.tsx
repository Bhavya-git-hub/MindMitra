import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AcademicsView, CourseDetailView } from "@/components/admin/academics-views";
import { AuditView } from "@/components/admin/audit-view";
import { AnalyticsView, OversightView } from "@/components/admin/insights-views";

import { expectNoA11yViolations } from "../helpers/a11y";
import { json, problem, renderWithApp } from "../helpers/render";
import { navigation } from "../helpers/navigation";
import {
  COURSE,
  DEPT,
  STUDENT,
  TEACHER,
  adminSession,
  auditEvent,
  course,
  department,
  oversight,
  platformAnalytics,
  student,
  teacher,
} from "../helpers/admin-data";

beforeEach(() => navigation.reset());
afterEach(() => vi.restoreAllMocks());

describe("departments", () => {
  const list = { "GET /admin/departments": () => json([department()]) };

  it("lists departments with their counts", async () => {
    const { container } = renderWithApp(<AcademicsView />, adminSession(list));
    const table = await screen.findByRole("table", { name: "Departments" });
    expect(within(table).getByRole("rowheader", { name: "Computer Science" })).toBeInTheDocument();
    expect(within(table).getByText("30")).toBeInTheDocument();
    await expectNoA11yViolations(container);
  });

  it("validates a new department, then creates it", async () => {
    const user = userEvent.setup();
    const posts: unknown[] = [];
    const session = adminSession({
      ...list,
      "POST /admin/departments": (call) => {
        posts.push(call.body);
        return json(department({ name: "Physics", code: "PHY" }), 201);
      },
    });
    renderWithApp(<AcademicsView />, session);
    await screen.findByRole("table", { name: "Departments" });
    await user.click(screen.getByRole("button", { name: "Add department" }));
    const dialog = await screen.findByRole("dialog", { name: "Add a department" });
    await user.type(within(dialog).getByLabelText("Short code"), "bad code!");
    await user.click(within(dialog).getByRole("button", { name: "Save" }));
    expect(within(dialog).getByText("Enter a name.")).toBeInTheDocument();
    expect(
      within(dialog).getByText("Use up to 20 letters, digits or hyphens."),
    ).toBeInTheDocument();
    expect(posts).toEqual([]);

    await user.type(within(dialog).getByLabelText("Name"), "Physics");
    await user.clear(within(dialog).getByLabelText("Short code"));
    await user.type(within(dialog).getByLabelText("Short code"), "PHY");
    await user.click(within(dialog).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(posts).toEqual([{ name: "Physics", code: "PHY" }]));
  });

  it("says why a department can't be deleted", async () => {
    const user = userEvent.setup();
    const session = adminSession({
      ...list,
      [`DELETE /admin/departments/${DEPT}`]: () =>
        problem(409, "The department still has students."),
    });
    renderWithApp(<AcademicsView />, session);
    await screen.findByRole("table", { name: "Departments" });
    await user.click(screen.getByRole("button", { name: /Delete/ }));
    const dialog = await screen.findByRole("alertdialog");
    await user.click(within(dialog).getByRole("button", { name: "Delete" }));
    expect(await screen.findByText("That department can't be deleted")).toBeInTheDocument();
    expect(await screen.findByText("The department still has students.")).toBeInTheDocument();
  });
});

describe("courses", () => {
  it("lists courses, filters by department and validates a new course", async () => {
    const user = userEvent.setup();
    const posts: unknown[] = [];
    const session = adminSession({
      "GET /admin/departments": () => json([department()]),
      "GET /admin/courses": () => json([course()]),
      "POST /admin/courses": (call) => {
        posts.push(call.body);
        return json(course(), 201);
      },
    });
    renderWithApp(<AcademicsView />, session);
    await user.click(await screen.findByRole("button", { name: "Courses" }));
    const table = await screen.findByRole("table", { name: "Courses" });
    expect(within(table).getByRole("link", { name: "CS101 Intro to Computing" })).toHaveAttribute(
      "href",
      `/admin/academics/courses/${COURSE}`,
    );
    await user.selectOptions(await screen.findByLabelText("Department"), DEPT);
    await waitFor(() =>
      expect(
        session.api.calls.some(
          (c) => c.path === "/admin/courses" && c.query.get("department_id") === DEPT,
        ),
      ).toBe(true),
    );

    await user.click(screen.getByRole("button", { name: "Add course" }));
    const dialog = await screen.findByRole("dialog", { name: "Add a course" });
    await user.click(await within(dialog).findByRole("button", { name: "Add course" }));
    expect(within(dialog).getByText("Choose a department.")).toBeInTheDocument();
    expect(within(dialog).getByText("Enter a course code.")).toBeInTheDocument();
    expect(posts).toEqual([]);
    await user.selectOptions(within(dialog).getByLabelText("Department"), DEPT);
    await user.type(within(dialog).getByLabelText("Course code"), "CS202");
    await user.type(within(dialog).getByLabelText("Title"), "Data structures");
    const term = within(dialog).getByLabelText("Term");
    await user.clear(term);
    await user.type(term, "2026-autumn");
    await user.click(within(dialog).getByRole("button", { name: "Add course" }));
    await waitFor(() => expect(posts).toHaveLength(1));
    expect(posts[0]).toEqual({
      department_id: DEPT,
      code: "CS202",
      title: "Data structures",
      term: "2026-autumn",
      credits: 3,
    });
  });
});

describe("course detail", () => {
  const detail = {
    course: course(),
    teachers: [{ id: TEACHER, full_name: "Asha Verma", number: "E-77" }],
    students: [{ id: STUDENT, full_name: "Aarini Chaudhary", number: "S-1001" }],
  };
  const other = student({ id: "0192d000-0000-7000-8000-0000000000aa", full_name: "Ishaan Rao" });
  const handlers = {
    [`GET /admin/courses/${COURSE}`]: () => json(detail),
    "GET /admin/teachers": () =>
      json({
        items: [
          teacher(),
          teacher({ id: "0192d000-0000-7000-8000-0000000000bb", full_name: "Kabir Shah" }),
        ],
        total: 2,
      }),
    "GET /admin/students": () => json({ items: [student(), other], total: 2 }),
  };

  it("shows who teaches and who is enrolled, and removes an enrolment", async () => {
    const user = userEvent.setup();
    let dropped = 0;
    const session = adminSession({
      ...handlers,
      [`DELETE /admin/courses/${COURSE}/students/${STUDENT}`]: () => {
        dropped += 1;
        return new Response(null, { status: 204 });
      },
    });
    const { container } = renderWithApp(<CourseDetailView id={COURSE} />, session);
    expect(await screen.findByText("Enrolled students (24)")).toBeInTheDocument();
    expect(screen.getByText(/E-77/)).toBeInTheDocument();
    await expectNoA11yViolations(container);
    await user.click(screen.getByRole("button", { name: /Remove\s*Aarini Chaudhary/ }));
    await waitFor(() => expect(dropped).toBe(1));
  });

  it("offers only teachers not already assigned, and assigns one", async () => {
    const user = userEvent.setup();
    let assigned = 0;
    const session = adminSession({
      ...handlers,
      [`PUT /admin/courses/${COURSE}/teachers/0192d000-0000-7000-8000-0000000000bb`]: () => {
        assigned += 1;
        return new Response(null, { status: 204 });
      },
    });
    renderWithApp(<CourseDetailView id={COURSE} />, session);
    const select = await screen.findByLabelText("Add a teacher");
    expect(within(select).queryByText(/Asha Verma/)).not.toBeInTheDocument();
    await user.selectOptions(select, "0192d000-0000-7000-8000-0000000000bb");
    await user.click(screen.getByRole("button", { name: "Add" }));
    await waitFor(() => expect(assigned).toBe(1));
  });

  it("searches for a student only after two letters and enrols them", async () => {
    const user = userEvent.setup();
    let enrolled = 0;
    const session = adminSession({
      ...handlers,
      [`PUT /admin/courses/${COURSE}/students/${other.id}`]: () => {
        enrolled += 1;
        return new Response(null, { status: 204 });
      },
    });
    renderWithApp(<CourseDetailView id={COURSE} />, session);
    const box = await screen.findByLabelText("Find a student to enrol");
    await user.type(box, "i");
    await new Promise((r) => setTimeout(r, 400));
    expect(session.api.calls.filter((c) => c.path === "/admin/students")).toHaveLength(0);
    await user.type(box, "s");
    await user.click(await screen.findByRole("button", { name: /Enrol\s*Ishaan Rao/ }));
    await waitFor(() => expect(enrolled).toBe(1));
    // The student already enrolled is not offered again.
    expect(screen.queryByRole("button", { name: /Enrol\s*Aarini/ })).not.toBeInTheDocument();
  });

  it("explains a refused deletion and stays on the page", async () => {
    const user = userEvent.setup();
    const session = adminSession({
      ...handlers,
      [`DELETE /admin/courses/${COURSE}`]: () => problem(409, "The course has enrolment history."),
    });
    renderWithApp(<CourseDetailView id={COURSE} />, session);
    await screen.findByText("Enrolled students (24)");
    await user.click(screen.getByRole("button", { name: "Delete" }));
    const dialog = await screen.findByRole("alertdialog");
    await user.click(within(dialog).getByRole("button", { name: "Delete" }));
    expect(await screen.findByText("That course can't be deleted")).toBeInTheDocument();
    expect(navigation.router.push).not.toHaveBeenCalled();
  });
});

describe("analytics and oversight", () => {
  it("writes small counts as words, never as numbers", async () => {
    const session = adminSession({
      "GET /admin/analytics": () => json(platformAnalytics()),
    });
    const { container } = renderWithApp(<AnalyticsView />, session);
    const table = await screen.findByRole("table", { name: "Appointments booked each week" });
    expect(within(table).getByText("14")).toBeInTheDocument();
    expect(within(table).getByText("Fewer than 5")).toBeInTheDocument();
    expect(screen.getByText(/shown as “fewer than 5”/)).toBeInTheDocument();
    await expectNoA11yViolations(container);
  });

  it("asks for the chosen window", async () => {
    const user = userEvent.setup();
    const session = adminSession({
      "GET /admin/analytics": () => json(platformAnalytics()),
    });
    renderWithApp(<AnalyticsView />, session);
    await screen.findByText("Student wellbeing");
    await user.click(screen.getByRole("button", { name: "12 weeks" }));
    await waitFor(() =>
      expect(session.api.calls.some((c) => c.query.get("weeks") === "12")).toBe(true),
    );
  });

  it("shows oversight as counts only, hiding small numbers", async () => {
    const session = adminSession({
      "GET /admin/appointments/oversight": () => json(oversight()),
    });
    const { container } = renderWithApp(<OversightView />, session);
    expect(await screen.findByText("Therapist workload")).toBeInTheDocument();
    expect(screen.getByText("Some hidden")).toBeInTheDocument();
    const outcomes = screen.getByRole("table", { name: "Appointments by outcome" });
    expect(within(outcomes).getByText("Fewer than 5")).toBeInTheDocument();
    expect(screen.getByText("Counts only.")).toBeInTheDocument();
    // No student is named anywhere on the page.
    expect(container.textContent).not.toMatch(/Aarini/);
    await expectNoA11yViolations(container);
  });
});

describe("audit log", () => {
  const actions = { "GET /admin/audit/actions": () => json(["user.update_status", "auth.login"]) };

  it("lists entries newest first and hides nothing but the content they never held", async () => {
    const session = adminSession({
      ...actions,
      "GET /admin/audit": () =>
        json([
          auditEvent(3),
          auditEvent(2, { outcome: "denied", action: "note.read", reason: "not_permitted" }),
        ]),
    });
    const { container } = renderWithApp(<AuditView />, session);
    const table = await screen.findByRole("table", { name: "Audit log entries" });
    expect(within(table).getByText("user.update_status")).toBeInTheDocument();
    expect(within(table).getByText("Refused")).toBeInTheDocument();
    expect(within(table).getAllByText(/before: active, after: suspended/)[0]).toBeInTheDocument();
    expect(screen.getByText("2 entries, newest first")).toBeInTheDocument();
    await expectNoA11yViolations(container);
  });

  it("applies filters as an inclusive day range", async () => {
    const user = userEvent.setup();
    const session = adminSession({ ...actions, "GET /admin/audit": () => json([auditEvent(1)]) });
    renderWithApp(<AuditView />, session);
    await screen.findByRole("table", { name: "Audit log entries" });
    await user.selectOptions(screen.getByLabelText("Outcome"), "denied");
    await user.type(screen.getByLabelText("From"), "2026-10-01");
    await user.type(screen.getByLabelText("To"), "2026-10-02");
    await user.click(screen.getByRole("button", { name: "Apply" }));
    await waitFor(() => {
      const call = session.api.calls.filter((c) => c.path === "/admin/audit").at(-1);
      expect(call?.query.get("outcome")).toBe("denied");
      expect(call?.query.get("since")).toBe("2026-10-01T00:00:00Z");
      expect(call?.query.get("until")).toBe("2026-10-03T00:00:00.000Z");
    });
  });

  it("loads older entries from the last one shown", async () => {
    const user = userEvent.setup();
    const page = Array.from({ length: 50 }, (_, i) => auditEvent(100 - i));
    const session = adminSession({
      ...actions,
      "GET /admin/audit": (call) => json(call.query.get("before_seq") ? [auditEvent(40)] : page),
    });
    renderWithApp(<AuditView />, session);
    await user.click(await screen.findByRole("button", { name: "Show older entries" }));
    expect(await screen.findByText("51 entries, newest first")).toBeInTheDocument();
    const older = session.api.calls.filter((c) => c.query.has("before_seq"));
    expect(older[0]?.query.get("before_seq")).toBe("51");
    // A short page means there is nothing older.
    expect(screen.queryByRole("button", { name: "Show older entries" })).not.toBeInTheDocument();
  });

  it("reports an intact log and an altered one differently", async () => {
    const user = userEvent.setup();
    let intact = true;
    const session = adminSession({
      ...actions,
      "GET /admin/audit": () => json([auditEvent(1)]),
      "POST /admin/audit/verify": () =>
        json({
          intact,
          first_bad_seq: intact ? null : 7,
          events: 120,
          checked_at: "2026-10-10T09:00:00Z",
        }),
    });
    renderWithApp(<AuditView />, session);
    await screen.findByRole("table", { name: "Audit log entries" });
    await user.click(screen.getByRole("button", { name: "Check the log is intact" }));
    expect(await screen.findByText("The log is intact")).toBeInTheDocument();
    intact = false;
    await user.click(screen.getByRole("button", { name: "Check the log is intact" }));
    expect(await screen.findByText("The log has been altered")).toBeInTheDocument();
    expect(screen.getByText(/Entry 7 does not match/)).toBeInTheDocument();
  });

  it("downloads the filtered log as CSV", async () => {
    const user = userEvent.setup();
    const create = vi.fn(() => "blob:audit");
    const revoke = vi.fn();
    Object.assign(URL, { createObjectURL: create, revokeObjectURL: revoke });
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    const session = adminSession({
      ...actions,
      "GET /admin/audit": () => json([auditEvent(1)]),
      "GET /admin/audit/export": () =>
        new Response("seq,action\n1,user.update_status\n", {
          headers: { "Content-Type": "text/csv" },
        }),
    });
    renderWithApp(<AuditView />, session);
    await screen.findByRole("table", { name: "Audit log entries" });
    await user.click(screen.getByRole("button", { name: "Download CSV" }));
    await waitFor(() => expect(click).toHaveBeenCalledTimes(1));
    expect(create).toHaveBeenCalledTimes(1);
    expect(revoke).toHaveBeenCalledWith("blob:audit");
  });

  it("shows a message when the log can't be loaded", async () => {
    const session = adminSession({
      ...actions,
      "GET /admin/audit": () => problem(403, "You can't view this."),
    });
    renderWithApp(<AuditView />, session);
    expect(await screen.findByText(/can't view this|couldn't/i)).toBeInTheDocument();
  });
});
