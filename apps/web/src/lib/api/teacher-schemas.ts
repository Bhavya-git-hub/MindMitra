/** Runtime schemas for the teacher-portal API responses (see services/api/app/api/schemas). */
import { z } from "zod";

export const WINDOW_WEEKS = [4, 8, 12] as const;
export type WindowWeeks = (typeof WINDOW_WEEKS)[number];

export const teacherSchema = z.object({
  id: z.string(),
  name: z.string(),
  title: z.string().nullable(),
  department_id: z.string(),
  department_name: z.string(),
});
export type TeacherInfo = z.infer<typeof teacherSchema>;

export const classSchema = z.object({
  id: z.string(),
  code: z.string(),
  title: z.string(),
  term: z.string(),
  department_name: z.string(),
  enrolled: z.number().int(),
});
export type TeacherClass = z.infer<typeof classSchema>;

export const rosterSchema = z.object({ student_id: z.string(), name: z.string() });
export type RosterStudent = z.infer<typeof rosterSchema>;

/** `shown` carries a percent (rounded to 5); every other state carries no number at all. */
export const shareSchema = z.object({
  state: z.enum(["shown", "few", "most", "hidden"]),
  percent: z.number().int().nullable(),
  text: z.string(),
});
export type Share = z.infer<typeof shareSchema>;

export const weekSchema = z.object({
  week_start: z.string(),
  students_reporting: z.string().nullable(),
  mood: z.number().nullable(),
  energy: z.number().nullable(),
  stress: z.number().nullable(),
  sleep_hours: z.number().nullable(),
  sleep_quality: z.number().nullable(),
  check_in: shareSchema,
  academic_stress: shareSchema,
  strain: shareSchema,
});
export type WeekFigures = z.infer<typeof weekSchema>;

export const analyticsSchema = z.object({
  label: z.string(),
  scope: z.enum(["class", "department"]),
  window_weeks: z.number().int(),
  state: z.enum(["ok", "too_small"]),
  students_contributing: z.string().nullable(),
  min_group_size: z.number().int(),
  weeks: z.array(weekSchema),
  stressors: z.array(z.object({ key: z.string(), share: shareSchema })),
  wellbeing: z.array(z.object({ key: z.string(), label: z.string(), share: shareSchema })),
  actions: z.array(z.object({ key: z.string(), title: z.string(), message: z.string() })),
  headline: z.array(z.string()),
  generated_at: z.string(),
  disclaimer: z.string(),
  strain_explainer: z.string(),
});
export type GroupAnalytics = z.infer<typeof analyticsSchema>;

export const classAnalyticsSchema = z.object({ group: classSchema, analytics: analyticsSchema });
export const departmentAnalyticsSchema = z.object({
  department_id: z.string(),
  analytics: analyticsSchema,
});

export const reportSchema = z.object({
  title: z.string(),
  generated_at: z.string(),
  window_weeks: z.number().int(),
  summary: z.array(z.string()),
  analytics: analyticsSchema,
  notes: z.array(z.string()),
});
export type GroupReport = z.infer<typeof reportSchema>;

export const dashboardSchema = z.object({
  teacher: teacherSchema,
  classes: z.array(classSchema),
  department: analyticsSchema,
  referrals: z.object({ received: z.number(), in_progress: z.number(), closed: z.number() }),
  open_support_requests: z.number().int(),
  new_support_requests: z.number().int(),
});
export type TeacherDashboard = z.infer<typeof dashboardSchema>;

export const REFERRAL_CATEGORIES = [
  ["academic_distress", "Struggling with coursework"],
  ["behaviour_change", "A change in how they seem"],
  ["wellbeing_concern", "A general wellbeing concern"],
  ["safety_concern", "A possible safety concern"],
] as const;
export const REFERRAL_URGENCIES = [
  ["routine", "Routine"],
  ["soon", "Soon"],
  ["urgent", "Urgent"],
] as const;
export const REFERRAL_OUTCOMES = [
  ["contacted_student", "Reached out to the student"],
  ["student_declined", "Student chose not to take it further"],
  ["already_supported", "Student already has support"],
  ["referred_elsewhere", "Pointed to another service"],
  ["no_action_needed", "No action needed"],
] as const;

export const referralSchema = z.object({
  id: z.string(),
  student_id: z.string(),
  student_name: z.string(),
  course_id: z.string(),
  course_code: z.string(),
  course_title: z.string(),
  category: z.string(),
  category_label: z.string(),
  urgency: z.string(),
  urgency_label: z.string(),
  note: z.string().nullable(),
  status: z.enum(["received", "in_progress", "closed"]),
  status_label: z.string(),
  created_at: z.string(),
});
export type Referral = z.infer<typeof referralSchema>;

export const referralDetailSchema = referralSchema.extend({ message: z.string() });

export const triageReferralSchema = referralSchema.extend({
  teacher_name: z.string(),
  department_name: z.string(),
  on_my_team: z.boolean(),
  claimed_by_me: z.boolean(),
  outcome: z.string().nullable(),
  outcome_label: z.string().nullable(),
  closed_at: z.string().nullable(),
  claimed_at: z.string().nullable(),
});
export type TriageReferral = z.infer<typeof triageReferralSchema>;

export const SUPPORT_TOPICS = [
  ["academic_support", "Help with the coursework"],
  ["workload", "The workload feels heavy"],
  ["extension", "Asking for more time"],
  ["wellbeing_chat", "A chat about how I am doing"],
  ["other", "Something else"],
] as const;

export const supportRequestSchema = z.object({
  id: z.string(),
  course_id: z.string(),
  course_code: z.string(),
  course_title: z.string(),
  teacher_name: z.string(),
  student_name: z.string(),
  topic: z.string(),
  topic_label: z.string(),
  message: z.string().nullable(),
  status: z.enum(["open", "acknowledged", "closed", "withdrawn"]),
  status_label: z.string(),
  created_at: z.string(),
});
export type SupportRequest = z.infer<typeof supportRequestSchema>;

export const courseOptionSchema = z.object({
  course_id: z.string(),
  code: z.string(),
  title: z.string(),
  teachers: z.array(
    z.object({ teacher_id: z.string(), name: z.string(), title: z.string().nullable() }),
  ),
});
export type CourseOption = z.infer<typeof courseOptionSchema>;
