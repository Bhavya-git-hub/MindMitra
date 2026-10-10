/** Runtime schemas for the administrator API responses (see services/api/app/api/schemas/admin.py). */
import { z } from "zod";

import { analyticsSchema } from "./teacher-schemas";

export const pageOf = <T extends z.ZodType>(item: T) =>
  z.object({ items: z.array(item), total: z.number().int() });

export const USER_STATUSES = ["active", "invited", "suspended", "deactivated"] as const;
export const ADMIN_ROLES = ["student", "teacher", "therapist", "administrator"] as const;
export type AdminRole = (typeof ADMIN_ROLES)[number];

export const userSchema = z.object({
  id: z.string(),
  email: z.string(),
  full_name: z.string(),
  role: z.string(),
  status: z.string(),
  created_at: z.string(),
  last_login_at: z.string().nullable(),
});
export type AdminUser = z.infer<typeof userSchema>;

export const institutionSchema = z.object({
  id: z.string(),
  name: z.string(),
  slug: z.string(),
  region: z.string(),
  email_domains: z.array(z.string()),
});
export type Institution = z.infer<typeof institutionSchema>;

// ---- structure ----
export const departmentSchema = z.object({
  id: z.string(),
  name: z.string(),
  code: z.string(),
  students: z.number().int(),
  teachers: z.number().int(),
  courses: z.number().int(),
});
export type Department = z.infer<typeof departmentSchema>;

export const courseSchema = z.object({
  id: z.string(),
  department_id: z.string(),
  department_name: z.string(),
  code: z.string(),
  title: z.string(),
  term: z.string(),
  credits: z.number().int(),
  teachers: z.number().int(),
  enrolled: z.number().int(),
});
export type Course = z.infer<typeof courseSchema>;

const personSchema = z.object({ id: z.string(), full_name: z.string(), number: z.string() });
export type CoursePerson = z.infer<typeof personSchema>;

export const courseDetailSchema = z.object({
  course: courseSchema,
  teachers: z.array(personSchema),
  students: z.array(personSchema),
});
export type CourseDetail = z.infer<typeof courseDetailSchema>;

// ---- people ----
export const studentSchema = z.object({
  id: z.string(),
  full_name: z.string(),
  email: z.string(),
  status: z.string(),
  student_number: z.string(),
  department_id: z.string(),
  department_name: z.string(),
  enrollment_year: z.number().int(),
  year_of_study: z.number().int(),
});
export type AdminStudent = z.infer<typeof studentSchema>;

export const studentDetailSchema = z.object({
  student: studentSchema,
  courses: z.array(
    z.object({
      course_id: z.string(),
      code: z.string(),
      title: z.string(),
      term: z.string(),
      status: z.string(),
    }),
  ),
});

export const teacherAccountSchema = z.object({
  id: z.string(),
  full_name: z.string(),
  email: z.string(),
  status: z.string(),
  employee_number: z.string(),
  title: z.string().nullable(),
  department_id: z.string(),
  department_name: z.string(),
  courses: z.number().int(),
});
export type AdminTeacher = z.infer<typeof teacherAccountSchema>;

export const therapistAccountSchema = z.object({
  id: z.string(),
  full_name: z.string(),
  email: z.string(),
  status: z.string(),
  licence_number: z.string(),
  verification_status: z.string(),
  accepting_new_students: z.boolean(),
  max_caseload: z.number().int(),
  caseload: z.number().int(),
});
export type AdminTherapist = z.infer<typeof therapistAccountSchema>;

export const reviewSchema = z.object({
  id: z.string(),
  full_name: z.string(),
  email: z.string(),
  licence_number: z.string(),
  licence_body: z.string().nullable(),
  licence_expires_on: z.string().nullable(),
  verification_status: z.string(),
  verified_at: z.string().nullable(),
  verification_note: z.string().nullable(),
});
export type TherapistReview = z.infer<typeof reviewSchema>;

// ---- resources ----
export const RESOURCE_TYPES = ["article", "video", "exercise", "audio", "service"] as const;

export const adminResourceSchema = z.object({
  id: z.string(),
  title: z.string(),
  summary: z.string(),
  body: z.string().nullable(),
  url: z.string().nullable(),
  resource_type: z.string(),
  tags: z.array(z.string()),
  language: z.string(),
  duration_minutes: z.number().int().nullable(),
  is_published: z.boolean(),
  source: z.enum(["global", "institution"]),
  audience: z.enum(["students", "faculty"]),
  editable: z.boolean(),
  reviewed_at: z.string().nullable(),
});
export type AdminResource = z.infer<typeof adminResourceSchema>;

// ---- dashboard, analytics, oversight ----
const accountCountsSchema = z.object({
  role: z.string(),
  active: z.number().int(),
  invited: z.number().int(),
  suspended: z.number().int(),
});

export const dashboardSchema = z.object({
  accounts: z.array(accountCountsSchema),
  pending_verifications: z.number().int(),
  licences_expiring: z.number().int(),
  draft_resources: z.number().int(),
  alerts_awaiting: z.number().int(),
  alerts_overdue: z.number().int(),
  denied_last_7_days: z.number().int(),
  generated_at: z.string(),
});
export type AdminDashboard = z.infer<typeof dashboardSchema>;

/** `count: null` means "fewer than 5": the API never sends a number from 1 to 4. */
const weekCountSchema = z.object({ week_start: z.string(), count: z.number().int().nullable() });
export type WeekCount = z.infer<typeof weekCountSchema>;

export const platformAnalyticsSchema = z.object({
  window_weeks: z.number().int(),
  accounts: z.array(accountCountsSchema),
  wellbeing: analyticsSchema,
  appointments_booked: z.array(weekCountSchema),
  alerts_raised: z.array(weekCountSchema),
  resources_published: z.record(z.string(), z.number().int()),
  small_number_note: z.string(),
  generated_at: z.string(),
});
export type PlatformAnalytics = z.infer<typeof platformAnalyticsSchema>;

export const oversightSchema = z.object({
  window_weeks: z.number().int(),
  by_status: z.array(z.object({ status: z.string(), count: z.number().int().nullable() })),
  weekly_scheduled: z.array(weekCountSchema),
  confirmed_next_7_days: z.number().int().nullable(),
  stale_requests: z.number().int(),
  therapists: z.array(
    z.object({
      therapist_id: z.string(),
      full_name: z.string(),
      upcoming: z.number().int(),
      completed: z.number().int(),
      no_shows: z.number().int(),
      cancelled: z.number().int(),
    }),
  ),
  note: z.string(),
  generated_at: z.string(),
});
export type Oversight = z.infer<typeof oversightSchema>;

// ---- audit ----
export const auditEventSchema = z.object({
  seq: z.number().int(),
  occurred_at: z.string(),
  actor_id: z.string().nullable(),
  actor_role: z.string().nullable(),
  action: z.string(),
  outcome: z.string(),
  resource_type: z.string().nullable(),
  resource_id: z.string().nullable(),
  subject_student_id: z.string().nullable(),
  reason: z.string().nullable(),
  details: z.record(z.string(), z.unknown()),
});
export type AuditEvent = z.infer<typeof auditEventSchema>;

export const chainStatusSchema = z.object({
  intact: z.boolean(),
  first_bad_seq: z.number().int().nullable(),
  events: z.number().int(),
  checked_at: z.string(),
});

// ---- settings ----
export const notificationSettingsSchema = z.object({
  values: z.object({
    reminders_enabled: z.boolean(),
    appointment_reminder_hours: z.array(z.number().int()),
    recommendation_notifications: z.boolean(),
    goal_reminders: z.boolean(),
    email_enabled: z.boolean(),
  }),
  fixed_rules: z.array(z.string()),
});
export type NotificationSettings = z.infer<typeof notificationSettingsSchema>;

export const safetySettingsSchema = z.object({
  values: z.object({
    alert_ack_minutes: z.number().int(),
    companion_enabled: z.boolean(),
    companion_daily_messages: z.number().int(),
  }),
  fixed_rules: z.array(z.string()),
});
export type SafetySettings = z.infer<typeof safetySettingsSchema>;

export const CONTACT_KINDS = ["emergency", "helpline", "campus"] as const;
export const crisisContactSchema = z.object({
  id: z.string(),
  label: z.string(),
  kind: z.string(),
  phone: z.string().nullable(),
  url: z.string().nullable(),
  description: z.string().nullable(),
  hours: z.string().nullable(),
  sort_order: z.number().int(),
  is_active: z.boolean(),
  editable: z.boolean(),
});
export type CrisisContact = z.infer<typeof crisisContactSchema>;
