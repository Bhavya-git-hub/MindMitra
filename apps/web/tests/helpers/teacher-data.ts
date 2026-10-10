/** Synthetic API payloads for the teacher-portal tests (no real people or data). */
import type {
  CourseOption,
  GroupAnalytics,
  Referral,
  Share,
  SupportRequest,
  TeacherClass,
  TeacherDashboard,
  TriageReferral,
  WeekFigures,
} from "@/lib/api/teacher-schemas";

import { makeSession, type TestSession } from "./render";

type Handlers = Parameters<typeof makeSession>[0];

export const teacherSession = (handlers: Handlers = {}): TestSession =>
  makeSession(handlers, { signedInAs: "teacher" });

export const COURSE_ID = "0192c000-0000-7000-8000-000000000001";
export const DEPT_ID = "0192c000-0000-7000-8000-000000000002";
export const STUDENT_ID = "0192c000-0000-7000-8000-000000000003";
export const REFERRAL_ID = "0192c000-0000-7000-8000-000000000004";
export const REQUEST_ID = "0192c000-0000-7000-8000-000000000005";
export const TEACHER_ID = "0192c000-0000-7000-8000-000000000006";

export const shown = (percent: number): Share => ({
  state: "shown",
  percent,
  text: `about ${percent}%`,
});
export const few: Share = { state: "few", percent: null, text: "a few students" };
export const most: Share = { state: "most", percent: null, text: "nearly all students" };
export const hidden: Share = {
  state: "hidden",
  percent: null,
  text: "not enough students to show",
};

export const week = (start: string, extra: Partial<WeekFigures> = {}): WeekFigures => ({
  week_start: start,
  students_reporting: "10 to 19",
  mood: 3.4,
  energy: 3.1,
  stress: 3.6,
  sleep_hours: 6.8,
  sleep_quality: 3.2,
  check_in: shown(70),
  academic_stress: shown(55),
  strain: few,
  ...extra,
});

export const analytics = (extra: Partial<GroupAnalytics> = {}): GroupAnalytics => ({
  label: "CS101 Intro to Computing",
  scope: "class",
  window_weeks: 8,
  state: "ok",
  students_contributing: "10 to 19",
  min_group_size: 10,
  weeks: [
    week("2026-09-14", {
      mood: null,
      energy: null,
      stress: null,
      sleep_hours: null,
      strain: hidden,
    }),
    week("2026-09-21"),
    week("2026-09-28", { mood: 3.2, stress: 3.9, strain: shown(20) }),
  ],
  stressors: [
    { key: "exams", share: shown(60) },
    { key: "finances", share: most },
  ],
  wellbeing: [
    { key: "doing_well", label: "Doing well", share: shown(40) },
    { key: "mixed", label: "Mixed", share: shown(35) },
    { key: "lower", label: "Lower lately", share: shown(25) },
  ],
  actions: [
    {
      key: "stress_rising",
      title: "Stress has been rising",
      message: "Spacing deadlines can take pressure off.",
    },
  ],
  headline: ["Average mood this week: 3.2 out of 5.", "Average stress this week: 3.9 out of 5."],
  generated_at: "2026-10-05T09:00:00Z",
  disclaimer: "These figures describe a group, not any person, and are not a diagnosis.",
  strain_explainer: "Signs of strain means two or more of low energy, high stress and short sleep.",
  ...extra,
});

export const tooSmall = (): GroupAnalytics =>
  analytics({
    state: "too_small",
    students_contributing: null,
    weeks: [],
    stressors: [],
    wellbeing: [],
    actions: [],
    headline: ["Too few students have chosen to share anonymous figures for this group."],
  });

export const teacherClass = (extra: Partial<TeacherClass> = {}): TeacherClass => ({
  id: COURSE_ID,
  code: "CS101",
  title: "Intro to Computing",
  term: "2026-autumn",
  department_name: "Computer Science",
  enrolled: 24,
  ...extra,
});

export const dashboard = (extra: Partial<TeacherDashboard> = {}): TeacherDashboard => ({
  teacher: {
    id: TEACHER_ID,
    name: "Asha Verma",
    title: "Lecturer",
    department_id: DEPT_ID,
    department_name: "Computer Science",
  },
  classes: [teacherClass()],
  department: analytics({ scope: "department", label: "Computer Science", window_weeks: 4 }),
  referrals: { received: 1, in_progress: 1, closed: 2 },
  open_support_requests: 2,
  new_support_requests: 1,
  ...extra,
});

export const referral = (extra: Partial<Referral> = {}): Referral => ({
  id: REFERRAL_ID,
  student_id: STUDENT_ID,
  student_name: "Aarini Chaudhary",
  course_id: COURSE_ID,
  course_code: "CS101",
  course_title: "Intro to Computing",
  category: "wellbeing_concern",
  category_label: "A general wellbeing concern",
  urgency: "routine",
  urgency_label: "Routine",
  note: "Has missed two classes.",
  status: "received",
  status_label: "Received by the wellbeing team",
  created_at: "2026-10-03T10:00:00Z",
  ...extra,
});

export const triage = (extra: Partial<TriageReferral> = {}): TriageReferral => ({
  ...referral(),
  teacher_name: "Asha Verma",
  department_name: "Computer Science",
  on_my_team: false,
  claimed_by_me: false,
  outcome: null,
  outcome_label: null,
  closed_at: null,
  claimed_at: null,
  ...extra,
});

export const supportRequest = (extra: Partial<SupportRequest> = {}): SupportRequest => ({
  id: REQUEST_ID,
  course_id: COURSE_ID,
  course_code: "CS101",
  course_title: "Intro to Computing",
  teacher_name: "Asha Verma",
  student_name: "Aarini Chaudhary",
  topic: "extension",
  topic_label: "Asking for more time",
  message: "Could I have two more days?",
  status: "open",
  status_label: "Waiting",
  created_at: "2026-10-04T10:00:00Z",
  ...extra,
});

export const courseOption = (): CourseOption => ({
  course_id: COURSE_ID,
  code: "CS101",
  title: "Intro to Computing",
  teachers: [{ teacher_id: TEACHER_ID, name: "Asha Verma", title: "Lecturer" }],
});
