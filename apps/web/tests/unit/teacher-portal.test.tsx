import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { TeacherSupportView } from "@/components/student/teacher-support-view";
import { AnalyticsPanel } from "@/components/teacher/analytics-panel";
import { ClassDetailView, ClassesView } from "@/components/teacher/classes-views";
import { TeacherDashboardView } from "@/components/teacher/dashboard-view";
import {
  NewReferralView,
  ReferralDetailView,
  ReferralsView,
} from "@/components/teacher/referrals-views";
import { TeacherResourcesView } from "@/components/teacher/resources-views";
import { SupportRequestsView } from "@/components/teacher/support-requests-view";
import { TrendsView } from "@/components/teacher/trends-view";
import { TriageReferralsView } from "@/components/therapist/referrals-view";

import { expectNoA11yViolations } from "../helpers/a11y";
import { json, problem, renderWithApp } from "../helpers/render";
import { navigation } from "../helpers/navigation";
import {
  COURSE_ID,
  DEPT_ID,
  REFERRAL_ID,
  REQUEST_ID,
  STUDENT_ID,
  TEACHER_ID,
  analytics,
  courseOption,
  dashboard,
  few,
  hidden,
  referral,
  supportRequest,
  teacherClass,
  teacherSession,
  tooSmall,
  triage,
} from "../helpers/teacher-data";
import { makeSession } from "../helpers/render";
import { profile } from "../helpers/therapist-data";

beforeEach(() => navigation.reset());

describe("group figures", () => {
  it("shows averages, shares and next steps for a group that is large enough", async () => {
    const { container } = renderWithApp(<AnalyticsPanel analytics={analytics()} />);
    expect(screen.getByText("Students contributing")).toBeInTheDocument();
    expect(screen.getAllByText("10 to 19").length).toBeGreaterThan(0);
    expect(screen.getByText("Stress has been rising")).toBeInTheDocument();
    expect(screen.getByText("about 60%")).toBeInTheDocument();
    expect(screen.getByText(/two or more of low energy/)).toBeInTheDocument();
    await expectNoA11yViolations(container);
  });

  it("describes small shares in words and never shows a count for them", () => {
    renderWithApp(<AnalyticsPanel analytics={analytics()} />);
    expect(screen.getAllByText("a few students").length).toBeGreaterThan(0);
    expect(screen.getByText("nearly all students")).toBeInTheDocument();
    expect(screen.getAllByText("Not enough students").length).toBeGreaterThan(0);
  });

  it("says why nothing is shown for a group that is too small, with no numbers", async () => {
    const { container } = renderWithApp(<AnalyticsPanel analytics={tooSmall()} />);
    expect(screen.getByText("Not enough students to show this group")).toBeInTheDocument();
    const text = container.textContent ?? "";
    expect(text).toMatch(/at least 10 students/);
    expect(text.replace("10", "")).not.toMatch(/\d/);
    expect(screen.queryByText(/Average mood/)).not.toBeInTheDocument();
    await expectNoA11yViolations(container);
  });

  it("explains a missing average instead of inventing one", () => {
    renderWithApp(
      <AnalyticsPanel
        analytics={analytics({
          weeks: [
            {
              ...analytics().weeks[1]!,
              mood: null,
              energy: null,
              stress: null,
              sleep_hours: null,
              strain: hidden,
              academic_stress: few,
            },
          ],
        })}
      />,
    );
    expect(screen.getByText(/No week in this window has enough students/)).toBeInTheDocument();
    expect(screen.getAllByText("—").length).toBeGreaterThanOrEqual(3);
  });
});

describe("teacher dashboard", () => {
  it("greets the teacher and shows group-level counts only", async () => {
    const { container } = renderWithApp(
      <TeacherDashboardView />,
      teacherSession({ "GET /teacher/dashboard": () => json(dashboard()) }),
    );
    expect(await screen.findByRole("heading", { level: 1, name: /Welcome, Asha/ })).toBeVisible();
    expect(screen.getByText("Open referrals")).toBeInTheDocument();
    expect(screen.getByText("1 waiting for you")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Intro to Computing" })).toHaveAttribute(
      "href",
      `/teacher/classes/${COURSE_ID}`,
    );
    expect(screen.getByText(/never shown to teachers/)).toBeInTheDocument();
    await expectNoA11yViolations(container);
  });

  it("shows a calm message when the department is too small to report", async () => {
    renderWithApp(
      <TeacherDashboardView />,
      teacherSession({
        "GET /teacher/dashboard": () => json(dashboard({ department: tooSmall() })),
      }),
    );
    expect(await screen.findByText("Not enough yet")).toBeInTheDocument();
    expect(screen.getByText(/Too few students/)).toBeInTheDocument();
  });
});

describe("classes and trends", () => {
  it("lists classes", async () => {
    renderWithApp(
      <ClassesView />,
      teacherSession({ "GET /teacher/classes": () => json([teacherClass()]) }),
    );
    expect(await screen.findByRole("link", { name: "Intro to Computing" })).toBeInTheDocument();
    expect(screen.getByText(/24 enrolled/)).toBeInTheDocument();
  });

  it("loads figures for the chosen window", async () => {
    const session = teacherSession({
      ["GET /teacher/classes/" + COURSE_ID]: () => json(teacherClass()),
      ["GET /teacher/classes/" + COURSE_ID + "/analytics"]: (call) =>
        json({
          group: teacherClass(),
          analytics: analytics({ window_weeks: Number(call.query.get("weeks")) }),
        }),
    });
    renderWithApp(<ClassDetailView id={COURSE_ID} />, session);
    expect(
      await screen.findByRole("heading", { level: 1, name: "Intro to Computing" }),
    ).toBeVisible();
    await screen.findByText("Supportive next steps");
    await userEvent.click(screen.getByRole("button", { name: "12 weeks" }));
    await waitFor(() =>
      expect(session.api.calls.some((c) => c.query.get("weeks") === "12")).toBe(true),
    );
    expect(screen.getByRole("link", { name: /Refer a student/ })).toHaveAttribute(
      "href",
      `/teacher/referrals/new?class=${COURSE_ID}`,
    );
  });

  it("shows only the teacher's own department on the trends page", async () => {
    const session = teacherSession({
      "GET /teacher/dashboard": () => json(dashboard()),
      ["GET /teacher/departments/" + DEPT_ID + "/analytics"]: () =>
        json({ department_id: DEPT_ID, analytics: analytics({ scope: "department" }) }),
    });
    renderWithApp(<TrendsView />, session);
    expect(await screen.findByText(/You can see your own department only/)).toBeInTheDocument();
    await screen.findByText("Supportive next steps");
    expect(session.api.calls.map((c) => c.path)).not.toContain("/teacher/departments/other");
  });

  it("downloads the CSV from the API", async () => {
    const created = vi.fn(() => "blob:report");
    vi.stubGlobal(
      "URL",
      Object.assign(URL, { createObjectURL: created, revokeObjectURL: vi.fn() }),
    );
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    const session = teacherSession({
      "GET /teacher/dashboard": () => json(dashboard()),
      ["GET /teacher/departments/" + DEPT_ID + "/analytics"]: () =>
        json({ department_id: DEPT_ID, analytics: analytics() }),
      ["GET /teacher/departments/" + DEPT_ID + "/report.csv"]: () =>
        new Response("week_start,mood\n", { headers: { "Content-Type": "text/csv" } }),
    });
    renderWithApp(<TrendsView />, session);
    await userEvent.click(await screen.findByRole("button", { name: /Download CSV/ }));
    await waitFor(() => expect(click).toHaveBeenCalled());
    expect(created).toHaveBeenCalled();
    const call = session.api.calls.find((c) => c.path.endsWith("report.csv"));
    expect(call?.query.get("weeks")).toBe("8");
    expect(call?.headers.get("Accept")).toBe("text/csv");
    click.mockRestore();
    vi.unstubAllGlobals();
  });
});

describe("referrals", () => {
  it("lists a teacher's own referrals with status only", async () => {
    renderWithApp(
      <ReferralsView />,
      teacherSession({ "GET /teacher/referrals": () => json([referral()]) }),
    );
    expect(await screen.findByRole("link", { name: "Aarini Chaudhary" })).toHaveAttribute(
      "href",
      `/teacher/referrals/${REFERRAL_ID}`,
    );
    expect(screen.getByText("Received by the wellbeing team")).toBeInTheDocument();
    expect(screen.getByText(/nothing about what happens next/)).toBeInTheDocument();
  });

  it("asks for what is missing before sending anything", async () => {
    const session = teacherSession({ "GET /teacher/classes": () => json([teacherClass()]) });
    renderWithApp(<NewReferralView />, session);
    await userEvent.click(await screen.findByRole("button", { name: "Send referral" }));
    expect(await screen.findByText("Choose a class.")).toBeInTheDocument();
    expect(screen.getByText("Choose a student.")).toBeInTheDocument();
    expect(screen.getByText("Choose what you have noticed.")).toBeInTheDocument();
    expect(
      session.api.calls.some((c) => c.path === "/teacher/referrals" && c.method === "POST"),
    ).toBe(false);
  });

  it("sends a referral for a student picked from the class roster", async () => {
    navigation.search = `class=${COURSE_ID}`;
    const session = teacherSession({
      "GET /teacher/classes": () => json([teacherClass()]),
      ["GET /teacher/classes/" + COURSE_ID + "/students"]: () =>
        json([{ student_id: STUDENT_ID, name: "Aarini Chaudhary" }]),
      "POST /teacher/referrals": () => json({ ...referral(), message: "In confidence." }, 201),
    });
    const { container } = renderWithApp(<NewReferralView />, session);
    await userEvent.selectOptions(await screen.findByLabelText("Student"), STUDENT_ID);
    await userEvent.selectOptions(
      screen.getByLabelText("What have you noticed?"),
      "wellbeing_concern",
    );
    await userEvent.type(screen.getByLabelText(/What you have seen/), "Quiet for two weeks.");
    await expectNoA11yViolations(container);
    await userEvent.click(screen.getByRole("button", { name: "Send referral" }));
    await waitFor(() =>
      expect(navigation.router.push).toHaveBeenCalledWith(`/teacher/referrals/${REFERRAL_ID}`),
    );
    const post = session.api.calls.find(
      (c) => c.path === "/teacher/referrals" && c.method === "POST",
    );
    expect(post?.body).toEqual({
      student_id: STUDENT_ID,
      course_id: COURSE_ID,
      category: "wellbeing_concern",
      urgency: "routine",
      note: "Quiet for two weeks.",
    });
  });

  it("shows the API's reason when a referral is refused", async () => {
    navigation.search = `class=${COURSE_ID}`;
    renderWithApp(
      <NewReferralView />,
      teacherSession({
        "GET /teacher/classes": () => json([teacherClass()]),
        ["GET /teacher/classes/" + COURSE_ID + "/students"]: () =>
          json([{ student_id: STUDENT_ID, name: "Aarini Chaudhary" }]),
        "POST /teacher/referrals": () =>
          problem(409, "You already have an open referral for this student."),
      }),
    );
    await userEvent.selectOptions(await screen.findByLabelText("Student"), STUDENT_ID);
    await userEvent.selectOptions(
      screen.getByLabelText("What have you noticed?"),
      "academic_distress",
    );
    await userEvent.click(screen.getByRole("button", { name: "Send referral" }));
    expect(await screen.findByText(/already have an open referral/)).toBeInTheDocument();
  });

  it("shows a referral's status and never anything about what happened to it", async () => {
    const { container } = renderWithApp(
      <ReferralDetailView id={REFERRAL_ID} />,
      teacherSession({
        ["GET /teacher/referrals/" + REFERRAL_ID]: () =>
          json({
            ...referral({ status: "in_progress", status_label: "With the wellbeing team" }),
            message: "Handled in confidence.",
          }),
      }),
    );
    expect(await screen.findByText("With the wellbeing team")).toBeInTheDocument();
    expect(screen.getByText("Handled in confidence.")).toBeInTheDocument();
    expect(screen.queryByText(/outcome/i)).not.toBeInTheDocument();
    await expectNoA11yViolations(container);
  });
});

describe("requests from students", () => {
  it("lets the teacher acknowledge and finish a request", async () => {
    let status: "open" | "acknowledged" = "open";
    const session = teacherSession({
      "GET /teacher/support-requests": () =>
        json([supportRequest({ status, status_label: status === "open" ? "Waiting" : "Seen" })]),
      ["POST /teacher/support-requests/" + REQUEST_ID + "/acknowledge"]: () => {
        status = "acknowledged";
        return json(supportRequest({ status, status_label: "Seen" }));
      },
    });
    const { container } = renderWithApp(<SupportRequestsView />, session);
    expect(await screen.findByText("Could I have two more days?")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "I've seen this" }));
    await waitFor(() => expect(screen.getByText("Seen")).toBeInTheDocument());
    expect(screen.queryByRole("button", { name: "I've seen this" })).not.toBeInTheDocument();
    await expectNoA11yViolations(container);
  });

  it("tells the teacher how little they see", async () => {
    renderWithApp(
      <SupportRequestsView />,
      teacherSession({ "GET /teacher/support-requests": () => json([]) }),
    );
    expect(await screen.findByText("Nothing waiting")).toBeInTheDocument();
    expect(screen.getByText(/Nothing else about them comes with it/)).toBeInTheDocument();
  });
});

describe("a student asking a teacher", () => {
  const studentHandlers = {
    "GET /me/teacher-support/options": () => json([courseOption()]),
    "GET /me/teacher-support": () => json([]),
  };

  it("says exactly what the teacher will see, and checks the form before sending", async () => {
    const session = makeSession(studentHandlers, { signedInAs: "student" });
    const { container } = renderWithApp(<TeacherSupportView />, session);
    expect(await screen.findByText(/can never see your check-ins, journal/)).toBeInTheDocument();
    await userEvent.click(await screen.findByRole("button", { name: "Send to my teacher" }));
    expect(await screen.findByText("Choose what you would like help with.")).toBeInTheDocument();
    expect(
      session.api.calls.some((c) => c.path === "/me/teacher-support" && c.method === "POST"),
    ).toBe(false);
    await expectNoA11yViolations(container);
  });

  it("sends a request to one of the student's own teachers", async () => {
    const session = makeSession(
      {
        ...studentHandlers,
        "POST /me/teacher-support": () => json(supportRequest(), 201),
      },
      { signedInAs: "student" },
    );
    renderWithApp(<TeacherSupportView />, session);
    await userEvent.selectOptions(await screen.findByLabelText("Teacher"), TEACHER_ID);
    await userEvent.selectOptions(screen.getByLabelText("What would help?"), "extension");
    await userEvent.type(screen.getByLabelText(/A few words/), "Could I have two more days?");
    await userEvent.click(screen.getByRole("button", { name: "Send to my teacher" }));
    await waitFor(() =>
      expect(
        session.api.calls.some((c) => c.path === "/me/teacher-support" && c.method === "POST"),
      ).toBe(true),
    );
    expect(
      session.api.calls.find((c) => c.path === "/me/teacher-support" && c.method === "POST")?.body,
    ).toEqual({
      course_id: COURSE_ID,
      teacher_id: TEACHER_ID,
      topic: "extension",
      message: "Could I have two more days?",
    });
  });

  it("lets a student withdraw a request", async () => {
    const session = makeSession(
      {
        "GET /me/teacher-support/options": () => json([courseOption()]),
        "GET /me/teacher-support": () => json([supportRequest()]),
        ["POST /me/teacher-support/" + REQUEST_ID + "/withdraw"]: () =>
          json(supportRequest({ status: "withdrawn", status_label: "Withdrawn by the student" })),
      },
      { signedInAs: "student" },
    );
    renderWithApp(<TeacherSupportView />, session);
    await userEvent.click(await screen.findByRole("button", { name: "Withdraw" }));
    await waitFor(() =>
      expect(session.api.calls.some((c) => c.path.endsWith("/withdraw"))).toBe(true),
    );
  });
});

describe("therapist triage of referrals", () => {
  const verified = { "GET /therapist/profile": () => json(profile()) };

  it("picks up a referral and closes it with an outcome", async () => {
    let status: "received" | "in_progress" = "received";
    const session = makeSession(
      {
        ...verified,
        "GET /therapist/referrals": () =>
          json([
            triage({
              status,
              status_label: status === "received" ? "Received" : "With the wellbeing team",
              claimed_by_me: status === "in_progress",
            }),
          ]),
        ["POST /therapist/referrals/" + REFERRAL_ID + "/claim"]: () => {
          status = "in_progress";
          return json(triage({ status, claimed_by_me: true }));
        },
        ["POST /therapist/referrals/" + REFERRAL_ID + "/close"]: () =>
          json(triage({ status: "in_progress", claimed_by_me: true })),
      },
      { signedInAs: "therapist" },
    );
    renderWithApp(<TriageReferralsView />, session);
    expect(await screen.findByText(/Has missed two classes/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Pick this up" }));
    await userEvent.click(await screen.findByRole("button", { name: "Close" }));
    const dialog = await screen.findByRole("dialog");
    await userEvent.click(within(dialog).getByRole("button", { name: "Close referral" }));
    expect(await within(dialog).findByText("Choose how this ended.")).toBeInTheDocument();
    await userEvent.selectOptions(
      within(dialog).getByLabelText("How did it end?"),
      "contacted_student",
    );
    await userEvent.click(within(dialog).getByRole("button", { name: "Close referral" }));
    await waitFor(() =>
      expect(session.api.calls.find((c) => c.path.endsWith("/close"))?.body).toEqual({
        outcome: "contacted_student",
      }),
    );
  });

  it("does not load referrals until the therapist is verified", async () => {
    const session = makeSession(
      {
        "GET /therapist/profile": () =>
          json(
            profile({
              can_see_students: false,
              verification_status: "pending",
              verification_label: "Waiting for verification",
            }),
          ),
      },
      { signedInAs: "therapist" },
    );
    renderWithApp(<TriageReferralsView />, session);
    expect(await screen.findByText(/stay closed until then/)).toBeInTheDocument();
    expect(session.api.calls.some((c) => c.path === "/therapist/referrals")).toBe(false);
  });
});

describe("faculty resources", () => {
  it("lists the staff library", async () => {
    const { container } = renderWithApp(
      <TeacherResourcesView />,
      teacherSession({
        "GET /teacher/resources": () =>
          json([
            {
              id: "0192c000-0000-7000-8000-0000000000a1",
              title: "When to refer a student",
              summary: "What a referral is.",
              resource_type: "article",
              tags: ["faculty"],
              duration_minutes: 6,
              url: null,
            },
          ]),
      }),
    );
    expect(await screen.findByRole("link", { name: "When to refer a student" })).toHaveAttribute(
      "href",
      "/teacher/resources/0192c000-0000-7000-8000-0000000000a1",
    );
    expect(screen.getByText("Resources for staff")).toBeInTheDocument();
    await expectNoA11yViolations(container);
  });
});

afterEach(() => vi.restoreAllMocks());
