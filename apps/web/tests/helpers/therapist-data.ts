/** Synthetic API payloads for the therapist-portal tests (no real people or data). */
import type {
  CaseloadStudent,
  RiskAlert,
  StudentProfile,
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
