/** Runtime schemas for the therapist-portal API responses (see services/api/app/api/schemas). */
import { z } from "zod";

import { trendPointSchema } from "./student-schemas";

export const VERIFICATION_STATUSES = ["pending", "verified", "rejected", "expired"] as const;

export const profileSchema = z.object({
  id: z.string(),
  full_name: z.string(),
  email: z.string(),
  bio: z.string().nullable(),
  specialties: z.array(z.string()),
  languages: z.array(z.string()),
  accepting_new_students: z.boolean(),
  max_caseload: z.number().int(),
  licence_number: z.string(),
  licence_body: z.string().nullable(),
  licence_expires_on: z.string().nullable(),
  verification_status: z.enum(VERIFICATION_STATUSES),
  verification_label: z.string(),
  verified_at: z.string().nullable(),
  verification_note: z.string().nullable(),
  can_see_students: z.boolean(),
});
export type TherapistProfile = z.infer<typeof profileSchema>;

export const slotSchema = z.object({
  id: z.string(),
  starts_at: z.string(),
  ends_at: z.string(),
  mode: z.string(),
  booked: z.boolean(),
  appointment_id: z.string().nullable(),
  appointment_status: z.string().nullable(),
});
export type AvailabilitySlot = z.infer<typeof slotSchema>;

export const appointmentSchema = z.object({
  id: z.string(),
  student_id: z.string(),
  therapist_id: z.string(),
  student_name: z.string(),
  starts_at: z.string(),
  ends_at: z.string(),
  mode: z.string(),
  status: z.string(),
  reason: z.string().nullable(),
  session_id: z.string().nullable(),
  can_start: z.boolean(),
  can_reschedule: z.boolean(),
  cancel_reason: z.string().nullable(),
  reschedule_count: z.number().int(),
  rescheduled_at: z.string().nullable(),
});
export type TherapistAppointment = z.infer<typeof appointmentSchema>;

export const sessionSchema = z.object({
  id: z.string(),
  appointment_id: z.string(),
  student_id: z.string(),
  student_name: z.string(),
  status: z.string(),
  started_at: z.string(),
  ended_at: z.string().nullable(),
  duration_minutes: z.number().int().nullable(),
  scheduled_start: z.string(),
  scheduled_end: z.string(),
  mode: z.string(),
  has_note: z.boolean(),
});
export type TherapySession = z.infer<typeof sessionSchema>;

export const noteSchema = z
  .object({
    session_id: z.string(),
    version: z.number().int(),
    body: z.string(),
    written_at: z.string(),
    latest: z.boolean(),
    versions: z.array(z.object({ version: z.number().int(), written_at: z.string() })),
  })
  .nullable();
export type TherapyNote = NonNullable<z.infer<typeof noteSchema>>;

const sharingSchema = z.object({ mood: z.boolean(), assessments: z.boolean() });
export type Sharing = z.infer<typeof sharingSchema>;

export const caseloadStudentSchema = z.object({
  student_id: z.string(),
  full_name: z.string(),
  preferred_name: z.string().nullable(),
  year_of_study: z.number().int(),
  care_role: z.string(),
  since: z.string(),
  next_appointment_at: z.string().nullable(),
  last_session_at: z.string().nullable(),
  open_alerts: z.number().int(),
  open_follow_ups: z.number().int(),
  sharing: sharingSchema,
});
export type CaseloadStudent = z.infer<typeof caseloadStudentSchema>;

export const studentProfileSchema = z.object({
  student_id: z.string(),
  full_name: z.string(),
  preferred_name: z.string().nullable(),
  pronouns: z.string().nullable(),
  department: z.string(),
  year_of_study: z.number().int(),
  care_role: z.string(),
  since: z.string(),
  sharing: sharingSchema,
  upcoming_appointments: z.array(appointmentSchema),
  recent_sessions: z.array(
    z.object({
      id: z.string(),
      status: z.string(),
      started_at: z.string(),
      duration_minutes: z.number().int().nullable(),
      has_note: z.boolean(),
    }),
  ),
  open_alerts: z.number().int(),
  open_follow_ups: z.number().int(),
  latest_mood: z.object({ score: z.number(), logged_at: z.string() }).nullable(),
  latest_assessment: z
    .object({ score: z.number(), max_score: z.number(), completed_at: z.string() })
    .nullable(),
  disclaimer: z.string(),
});
export type StudentProfile = z.infer<typeof studentProfileSchema>;

export const trendsSchema = z.object({
  days: z.number().int(),
  points: z.array(trendPointSchema),
  disclaimer: z.string(),
});

export const assessmentSchema = z.object({
  id: z.string(),
  instrument: z.string(),
  score: z.number(),
  max_score: z.number(),
  completed_at: z.string(),
});
export type StudentAssessment = z.infer<typeof assessmentSchema>;

export const alertSchema = z.object({
  id: z.string(),
  student_id: z.string(),
  student_name: z.string(),
  severity: z.string(),
  status: z.string(),
  category: z.string(),
  category_label: z.string(),
  source_label: z.string(),
  created_at: z.string(),
  sla_ack_due_at: z.string().nullable(),
  acknowledged_at: z.string().nullable(),
  resolved_at: z.string().nullable(),
  outcome: z.string().nullable(),
  assigned_to_me: z.boolean(),
  overdue: z.boolean(),
  excerpt: z.string().nullable(),
  disclaimer: z.string(),
});
export type RiskAlert = z.infer<typeof alertSchema>;

export const ALERT_OUTCOMES = [
  ["contacted_student", "I contacted the student"],
  ["session_booked", "A session was booked"],
  ["referred_elsewhere", "Referred to another service"],
  ["emergency_services", "Emergency services were involved"],
  ["no_action_needed", "No action was needed"],
] as const;

export const FOLLOW_UP_KINDS = [
  ["check_in", "Check in"],
  ["book_session", "Book a session"],
  ["referral", "Referral"],
  ["paperwork", "Paperwork"],
  ["other", "Other"],
] as const;
export type FollowUpKind = (typeof FOLLOW_UP_KINDS)[number][0];

export const followUpSchema = z.object({
  id: z.string(),
  student_id: z.string(),
  student_name: z.string(),
  session_id: z.string().nullable(),
  kind: z.string(),
  status: z.string(),
  due_on: z.string(),
  note: z.string().nullable(),
  completed_at: z.string().nullable(),
  overdue: z.boolean(),
});
export type FollowUp = z.infer<typeof followUpSchema>;

export const madeRecommendationSchema = z.object({
  id: z.string(),
  title: z.string(),
  rationale: z.string(),
  status: z.string(),
  resource_id: z.string().nullable(),
  resource_title: z.string().nullable(),
  created_at: z.string(),
  expires_at: z.string().nullable(),
});
export type MadeRecommendation = z.infer<typeof madeRecommendationSchema>;

export const dashboardSchema = z.object({
  verification_status: z.enum(VERIFICATION_STATUSES),
  verification_label: z.string(),
  can_see_students: z.boolean(),
  accepting_new_students: z.boolean(),
  caseload: z.number().int(),
  max_caseload: z.number().int(),
  today: z.array(appointmentSchema),
  next_appointment: appointmentSchema.nullable(),
  pending_requests: z.number().int(),
  alerts_by_severity: z.record(z.string(), z.number().int()),
  alerts_overdue: z.number().int(),
  follow_ups_due_today: z.number().int(),
  follow_ups_overdue: z.number().int(),
  unread_messages: z.number().int(),
});
export type TherapistDashboard = z.infer<typeof dashboardSchema>;

// ---- analytics (GET /therapist/analytics): counts and averages only, never a person ---------

const counts = z.record(z.string(), z.number().int());
const weekCount = z.object({ week_start: z.string(), count: z.number().int() });

export const therapistAnalyticsSchema = z.object({
  weeks: z.number().int(),
  window_start: z.string(),
  window_end: z.string(),
  caseload: z.object({
    caseload_size: z.number().int(),
    sharing_count: z.number().int(),
    weekly: z.array(
      z.object({
        week_start: z.string(),
        students_reporting: z.number().int(),
        mood_avg: z.number().nullable(),
        stress_avg: z.number().nullable(),
        sleep_hours_avg: z.number().nullable(),
      }),
    ),
  }),
  appointments: z.object({
    by_status: counts,
    weekly: z.array(
      z.object({
        week_start: z.string(),
        scheduled: z.number().int(),
        completed: z.number().int(),
        no_show: z.number().int(),
        cancelled: z.number().int(),
      }),
    ),
    rates: z.object({
      completion: z.number().int().nullable(),
      no_show: z.number().int().nullable(),
      cancellation: z.number().int().nullable(),
    }),
    by_mode: counts,
  }),
  interventions: z.object({
    recommendations: z.object({
      total: z.number().int(),
      by_status: counts,
      completion_rate: z.number().int().nullable(),
      weekly: z.array(weekCount),
    }),
    follow_ups: z.object({
      total: z.number().int(),
      by_status: counts,
      overdue: z.number().int(),
      done_on_time_rate: z.number().int().nullable(),
      by_kind: counts,
    }),
  }),
  alerts: z.object({
    total: z.number().int(),
    by_severity: counts,
    by_status: counts,
    weekly: z.array(weekCount),
    acknowledged_median_minutes: z.number().nullable(),
    overdue_open: z.number().int(),
    resolved_count: z.number().int(),
  }),
  generated_at: z.string(),
  disclaimer: z.string(),
});
export type TherapistAnalytics = z.infer<typeof therapistAnalyticsSchema>;
