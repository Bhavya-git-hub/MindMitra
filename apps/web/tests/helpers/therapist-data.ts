/** Synthetic API payloads for the therapist-portal tests (no real people or data). */
import type {
  CaseloadStudent,
  RiskAlert,
  StudentProfile,
  TherapistAnalytics,
  TherapistAppointment,
  TherapistDashboard,
  TherapistProfile,
  TherapySession,
} from "@/lib/api/therapist-schemas";

import { makeSession, type TestSession } from "./render";

type Handlers = Parameters<typeof makeSession>[0];

/** A signed-in therapist whose API answers `handlers` (and nothing else). */
export function therapistSession(handlers: Handlers = {}): TestSession {
  return makeSession(handlers, { signedInAs: "therapist" });
}

export const STUDENT_ID = "0192b000-0000-7000-8000-000000000001";
export const SESSION_ID = "0192b000-0000-7000-8000-0000000000c1";
export const ALERT_ID = "0192b000-0000-7000-8000-0000000000d1";
export const APPOINTMENT_ID = "0192b000-0000-7000-8000-0000000000e1";

export const profile = (extra: Partial<TherapistProfile> = {}): TherapistProfile => ({
  id: "0192b000-0000-7000-8000-000000000099",
  full_name: "Dr. Priya Nair",
  email: "priya.nair@care.test.example",
  bio: null,
  specialties: ["Anxiety"],
  languages: ["English"],
  accepting_new_students: true,
  max_caseload: 25,
  licence_number: "SYN-1234",
  licence_body: "Synthetic Council",
  licence_expires_on: "2028-01-01",
  verification_status: "verified",
  verification_label: "Verified",
  verified_at: "2026-09-01T09:00:00Z",
  verification_note: null,
  can_see_students: true,
  ...extra,
});

export const pendingProfile = (): TherapistProfile =>
  profile({
    verification_status: "pending",
    verification_label: "Waiting for verification",
    verified_at: null,
    can_see_students: false,
  });

export const caseloadStudent = (extra: Partial<CaseloadStudent> = {}): CaseloadStudent => ({
  student_id: STUDENT_ID,
  full_name: "Aarini Chaudhary",
  preferred_name: "Aarini",
  year_of_study: 2,
  care_role: "primary",
  since: "2026-08-01",
  next_appointment_at: null,
  last_session_at: null,
  open_alerts: 0,
  open_follow_ups: 0,
  sharing: { mood: true, assessments: false },
  ...extra,
});

export const studentProfile = (extra: Partial<StudentProfile> = {}): StudentProfile => ({
  student_id: STUDENT_ID,
  full_name: "Aarini Chaudhary",
  preferred_name: "Aarini",
  pronouns: null,
  department: "Computer Science",
  year_of_study: 2,
  care_role: "primary",
  since: "2026-08-01",
  sharing: { mood: false, assessments: false },
  upcoming_appointments: [],
  recent_sessions: [],
  open_alerts: 0,
  open_follow_ups: 0,
  latest_mood: null,
  latest_assessment: null,
  disclaimer: "Self-reported numbers are not a diagnosis.",
  ...extra,
});

export const appointment = (extra: Partial<TherapistAppointment> = {}): TherapistAppointment => ({
  id: APPOINTMENT_ID,
  student_id: STUDENT_ID,
  therapist_id: "0192b000-0000-7000-8000-000000000099",
  student_name: "Aarini Chaudhary",
  starts_at: "2026-10-14T10:00:00Z",
  ends_at: "2026-10-14T10:50:00Z",
  mode: "video",
  status: "requested",
  reason: null,
  session_id: null,
  can_start: false,
  can_reschedule: true,
  cancel_reason: null,
  reschedule_count: 0,
  rescheduled_at: null,
  ...extra,
});

export const session = (extra: Partial<TherapySession> = {}): TherapySession => ({
  id: SESSION_ID,
  appointment_id: APPOINTMENT_ID,
  student_id: STUDENT_ID,
  student_name: "Aarini Chaudhary",
  status: "in_progress",
  started_at: "2026-10-14T10:01:00Z",
  ended_at: null,
  duration_minutes: null,
  scheduled_start: "2026-10-14T10:00:00Z",
  scheduled_end: "2026-10-14T10:50:00Z",
  mode: "video",
  has_note: false,
  ...extra,
});

export const alert = (extra: Partial<RiskAlert> = {}): RiskAlert => ({
  id: ALERT_ID,
  student_id: STUDENT_ID,
  student_name: "Aarini Chaudhary",
  severity: "high",
  status: "open",
  category: "help_request",
  category_label: "Asked for help",
  source_label: "Student request",
  created_at: "2026-10-10T07:00:00Z",
  sla_ack_due_at: "2026-10-10T09:00:00Z",
  acknowledged_at: null,
  resolved_at: null,
  outcome: null,
  assigned_to_me: true,
  overdue: false,
  excerpt: null,
  disclaimer: "An alert is a prompt for care, not a diagnosis.",
  ...extra,
});

export const dashboard = (extra: Partial<TherapistDashboard> = {}): TherapistDashboard => ({
  verification_status: "verified",
  verification_label: "Verified",
  can_see_students: true,
  accepting_new_students: true,
  caseload: 4,
  max_caseload: 25,
  today: [],
  next_appointment: null,
  pending_requests: 2,
  alerts_by_severity: { high: 1 },
  alerts_overdue: 0,
  follow_ups_due_today: 1,
  follow_ups_overdue: 0,
  unread_messages: 3,
  ...extra,
});

const WEEK_STARTS = ["2026-09-14", "2026-09-21", "2026-09-28", "2026-10-05"];

/** Four finished weeks of counts and averages; the last two weeks hold the figures. */
export const analytics = (extra: Partial<TherapistAnalytics> = {}): TherapistAnalytics => ({
  weeks: 4,
  window_start: "2026-09-14",
  window_end: "2026-10-11",
  caseload: {
    caseload_size: 5,
    sharing_count: 3,
    weekly: WEEK_STARTS.map((week_start, i) => ({
      week_start,
      students_reporting: i >= 2 ? 3 : 0,
      mood_avg: i >= 2 ? 3.5 + (i - 2) / 2 : null,
      stress_avg: i >= 2 ? 2.5 : null,
      sleep_hours_avg: i >= 2 ? 7.25 : null,
    })),
  },
  appointments: {
    by_status: { requested: 0, confirmed: 1, completed: 6, cancelled: 2, no_show: 1 },
    weekly: WEEK_STARTS.map((week_start, i) => ({
      week_start,
      scheduled: i === 3 ? 4 : 2,
      completed: i === 3 ? 3 : 1,
      no_show: i === 3 ? 0 : 1,
      cancelled: i === 2 ? 1 : 0,
    })),
    rates: { completion: 67, no_show: 11, cancellation: 22 },
    by_mode: { video: 7, in_person: 2, phone: 1 },
  },
  interventions: {
    recommendations: {
      total: 5,
      by_status: { pending: 2, viewed: 1, dismissed: 0, completed: 2 },
      completion_rate: 40,
      weekly: WEEK_STARTS.map((week_start, i) => ({ week_start, count: i })),
    },
    follow_ups: {
      total: 4,
      by_status: { open: 2, done: 1, cancelled: 1 },
      overdue: 1,
      done_on_time_rate: 100,
      by_kind: { check_in: 3, book_session: 1, referral: 0, paperwork: 0, other: 0 },
    },
  },
  alerts: {
    total: 3,
    by_severity: { low: 1, moderate: 1, high: 1, imminent: 0 },
    by_status: {
      open: 1,
      acknowledged: 1,
      escalated: 0,
      in_progress: 0,
      resolved: 1,
      dismissed: 0,
    },
    weekly: WEEK_STARTS.map((week_start, i) => ({
      week_start,
      count: i === 1 ? 2 : i === 3 ? 1 : 0,
    })),
    acknowledged_median_minutes: 75,
    overdue_open: 1,
    resolved_count: 1,
  },
  generated_at: "2026-10-11T08:00:00Z",
  disclaimer: "Counts and averages only. Self-reported, not a diagnosis.",
  ...extra,
});

/** A therapist with nobody on their caseload and nothing done yet. */
export const emptyAnalytics = (weeks = 4): TherapistAnalytics => {
  const base = analytics({ weeks });
  const zero = (counts: Record<string, number>) =>
    Object.fromEntries(Object.keys(counts).map((k) => [k, 0]));
  return {
    ...base,
    caseload: {
      caseload_size: 0,
      sharing_count: 0,
      weekly: base.caseload.weekly.map((w) => ({
        week_start: w.week_start,
        students_reporting: 0,
        mood_avg: null,
        stress_avg: null,
        sleep_hours_avg: null,
      })),
    },
    appointments: {
      by_status: zero(base.appointments.by_status),
      weekly: base.appointments.weekly.map((w) => ({
        week_start: w.week_start,
        scheduled: 0,
        completed: 0,
        no_show: 0,
        cancelled: 0,
      })),
      rates: { completion: null, no_show: null, cancellation: null },
      by_mode: zero(base.appointments.by_mode),
    },
    interventions: {
      recommendations: {
        total: 0,
        by_status: zero(base.interventions.recommendations.by_status),
        completion_rate: null,
        weekly: base.interventions.recommendations.weekly.map((w) => ({ ...w, count: 0 })),
      },
      follow_ups: {
        total: 0,
        by_status: zero(base.interventions.follow_ups.by_status),
        overdue: 0,
        done_on_time_rate: null,
        by_kind: zero(base.interventions.follow_ups.by_kind),
      },
    },
    alerts: {
      total: 0,
      by_severity: zero(base.alerts.by_severity),
      by_status: zero(base.alerts.by_status),
      weekly: base.alerts.weekly.map((w) => ({ ...w, count: 0 })),
      acknowledged_median_minutes: null,
      overdue_open: 0,
      resolved_count: 0,
    },
  };
};
