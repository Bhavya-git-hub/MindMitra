/** Synthetic API payloads for the administrator-portal tests (no real people or data). */
import type {
  AdminDashboard,
  AdminResource,
  AdminStudent,
  AdminTeacher,
  AdminTherapist,
  AdminUser,
  AuditEvent,
  Course,
  CrisisContact,
  Department,
  Oversight,
  PlatformAnalytics,
  TherapistReview,
} from "@/lib/api/admin-schemas";

import { analytics } from "./teacher-data";
import { makeSession, type TestSession } from "./render";

type Handlers = Parameters<typeof makeSession>[0];

export const adminSession = (handlers: Handlers = {}): TestSession =>
  makeSession(handlers, { signedInAs: "administrator" });

export const ID = (n: number) => `0192d000-0000-7000-8000-${String(n).padStart(12, "0")}`;
export const DEPT = ID(1);
export const COURSE = ID(2);
export const STUDENT = ID(3);
export const TEACHER = ID(4);
export const THERAPIST = ID(5);
export const RESOURCE = ID(6);
export const CONTACT = ID(7);
/** The signed-in administrator in `me()` is `user-1`. */
export const SELF = "user-1";

export const department = (extra: Partial<Department> = {}): Department => ({
  id: DEPT,
  name: "Computer Science",
  code: "CS",
  students: 30,
  teachers: 3,
  courses: 4,
  ...extra,
});

export const course = (extra: Partial<Course> = {}): Course => ({
  id: COURSE,
  department_id: DEPT,
  department_name: "Computer Science",
  code: "CS101",
  title: "Intro to Computing",
  term: "2026-autumn",
  credits: 3,
  teachers: 1,
  enrolled: 24,
  ...extra,
});

export const student = (extra: Partial<AdminStudent> = {}): AdminStudent => ({
  id: STUDENT,
  full_name: "Aarini Chaudhary",
  email: "aarini@college.example",
  status: "active",
  student_number: "S-1001",
  department_id: DEPT,
  department_name: "Computer Science",
  enrollment_year: 2025,
  year_of_study: 2,
  ...extra,
});

export const teacher = (extra: Partial<AdminTeacher> = {}): AdminTeacher => ({
  id: TEACHER,
  full_name: "Asha Verma",
  email: "asha@college.example",
  status: "active",
  employee_number: "E-77",
  title: "Lecturer",
  department_id: DEPT,
  department_name: "Computer Science",
  courses: 2,
  ...extra,
});

export const therapist = (extra: Partial<AdminTherapist> = {}): AdminTherapist => ({
  id: THERAPIST,
  full_name: "Dr Meera Rao",
  email: "meera@care.example",
  status: "active",
  licence_number: "L-2200",
  verification_status: "verified",
  accepting_new_students: true,
  max_caseload: 40,
  caseload: 12,
  ...extra,
});

export const user = (extra: Partial<AdminUser> = {}): AdminUser => ({
  id: STUDENT,
  email: "aarini@college.example",
  full_name: "Aarini Chaudhary",
  role: "student",
  status: "active",
  created_at: "2026-08-01T09:00:00Z",
  last_login_at: "2026-10-05T09:00:00Z",
  ...extra,
});

export const review = (extra: Partial<TherapistReview> = {}): TherapistReview => ({
  id: THERAPIST,
  full_name: "Dr Meera Rao",
  email: "meera@care.example",
  licence_number: "L-2200",
  licence_body: "State Council of Psychologists",
  licence_expires_on: "2027-03-31",
  verification_status: "pending",
  verified_at: null,
  verification_note: null,
  ...extra,
});

export const resource = (extra: Partial<AdminResource> = {}): AdminResource => ({
  id: RESOURCE,
  title: "Box breathing",
  summary: "A four-count breathing exercise.",
  body: "Breathe in for four.",
  url: null,
  resource_type: "exercise",
  tags: ["calm"],
  language: "en",
  duration_minutes: 5,
  is_published: false,
  source: "institution",
  audience: "students",
  editable: true,
  reviewed_at: null,
  ...extra,
});

export const dashboard = (extra: Partial<AdminDashboard> = {}): AdminDashboard => ({
  accounts: [
    { role: "student", active: 120, invited: 4, suspended: 1 },
    { role: "teacher", active: 9, invited: 0, suspended: 0 },
    { role: "therapist", active: 5, invited: 1, suspended: 0 },
    { role: "administrator", active: 2, invited: 0, suspended: 0 },
  ],
  pending_verifications: 2,
  licences_expiring: 1,
  draft_resources: 3,
  alerts_awaiting: 1,
  alerts_overdue: 0,
  denied_last_7_days: 6,
  generated_at: "2026-10-10T09:00:00Z",
  ...extra,
});

export const platformAnalytics = (extra: Partial<PlatformAnalytics> = {}): PlatformAnalytics => ({
  window_weeks: 8,
  accounts: dashboard().accounts,
  wellbeing: analytics({ scope: "institution", label: "Synthetic College" }),
  appointments_booked: [
    { week_start: "2026-09-21", count: 14 },
    { week_start: "2026-09-28", count: null },
  ],
  alerts_raised: [
    { week_start: "2026-09-21", count: 0 },
    { week_start: "2026-09-28", count: null },
  ],
  resources_published: { article: 4, exercise: 2 },
  small_number_note: "Weekly counts of 1 to 4 are shown as “fewer than 5”.",
  generated_at: "2026-10-10T09:00:00Z",
  ...extra,
});

export const oversight = (extra: Partial<Oversight> = {}): Oversight => ({
  window_weeks: 8,
  by_status: [
    { status: "completed", count: 40 },
    { status: "cancelled", count: null },
  ],
  weekly_scheduled: [
    { week_start: "2026-09-21", count: 12 },
    { week_start: "2026-09-28", count: null },
  ],
  confirmed_next_7_days: 9,
  stale_requests: 2,
  therapists: [
    {
      therapist_id: THERAPIST,
      full_name: "Dr Meera Rao",
      upcoming: 4,
      completed: 30,
      no_shows: 1,
      cancelled: 2,
    },
  ],
  note: "Counts only.",
  generated_at: "2026-10-10T09:00:00Z",
  ...extra,
});

export const auditEvent = (seq: number, extra: Partial<AuditEvent> = {}): AuditEvent => ({
  seq,
  occurred_at: "2026-10-09T10:00:00Z",
  actor_id: "0192d000-aaaa-7000-8000-000000000001",
  actor_role: "administrator",
  action: "user.update_status",
  outcome: "allowed",
  resource_type: "user",
  resource_id: STUDENT,
  subject_student_id: null,
  reason: null,
  details: { before: "active", after: "suspended" },
  ...extra,
});

export const contact = (extra: Partial<CrisisContact> = {}): CrisisContact => ({
  id: CONTACT,
  label: "Campus counselling",
  kind: "campus",
  phone: "0000 000 000",
  url: null,
  description: null,
  hours: "9-5",
  sort_order: 100,
  is_active: true,
  editable: true,
  ...extra,
});

export const notificationSettings = () => ({
  values: {
    reminders_enabled: true,
    appointment_reminder_hours: [24, 2],
    recommendation_notifications: true,
    goal_reminders: true,
    email_enabled: false,
  },
  fixed_rules: ["Safety alerts are always shown in the app."],
});

export const safetySettings = () => ({
  values: { alert_ack_minutes: 15, companion_enabled: true, companion_daily_messages: 100 },
  fixed_rules: ["At least one emergency contact must stay active."],
});
