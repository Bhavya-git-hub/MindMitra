/** Runtime schemas for the student-portal API responses (see services/api/app/api/schemas). */
import { z } from "zod";

const nullableNumber = z.number().nullable();
const direction = z.enum(["up", "steady", "down"]).nullable();

export const supportInfoSchema = z.object({ message: z.string(), help_path: z.string() });
export type SupportInfo = z.infer<typeof supportInfoSchema>;

export const moodEntrySchema = z.object({
  id: z.string(),
  mood_score: z.number().int(),
  energy_level: z.number().int().nullable(),
  emotions: z.array(z.string()),
  note: z.string().nullish(),
  logged_at: z.string(),
});
export type MoodEntry = z.infer<typeof moodEntrySchema>;

export const stressEntrySchema = z.object({
  id: z.string(),
  stress_level: z.number().int(),
  stressors: z.array(z.string()),
  logged_at: z.string(),
});
export type StressEntry = z.infer<typeof stressEntrySchema>;

export const sleepEntrySchema = z.object({
  id: z.string(),
  sleep_date: z.string(),
  bedtime: z.string(),
  wake_time: z.string(),
  duration_minutes: z.number().int(),
  quality: z.number().int(),
});
export type SleepEntry = z.infer<typeof sleepEntrySchema>;

export const checkInResultSchema = z.object({
  mood: moodEntrySchema,
  stress: stressEntrySchema.nullable(),
  sleep: sleepEntrySchema.nullable(),
  support: supportInfoSchema.nullable(),
});
export type CheckInResult = z.infer<typeof checkInResultSchema>;

const indicatorSchema = z.object({ key: z.string(), label: z.string() }).nullable();

const metricSchema = z.object({
  today: nullableNumber,
  average_7d: nullableNumber,
  indicator: indicatorSchema,
  direction,
});
export type Metric = z.infer<typeof metricSchema>;

const sleepMetricSchema = z.object({
  last_night_minutes: nullableNumber,
  last_night_quality: nullableNumber,
  average_minutes_7d: nullableNumber,
  indicator: indicatorSchema,
  direction,
});

export const assessmentSnapshotSchema = z.object({
  id: z.string(),
  score: z.number(),
  max_score: z.number(),
  percent: z.number(),
  band: z.object({ key: z.string(), label: z.string(), message: z.string() }),
  completed_at: z.string(),
});
export type AssessmentSnapshot = z.infer<typeof assessmentSnapshotSchema>;

export const wellnessSummarySchema = z.object({
  date: z.string(),
  check_in: z.object({
    done_today: z.boolean(),
    streak_days: z.number().int(),
    check_ins_last_7d: z.number().int(),
    days_since_last: z.number().int().nullable(),
    emotions_today: z.array(z.string()),
  }),
  mood: metricSchema,
  stress: metricSchema,
  sleep: sleepMetricSchema,
  wellbeing: assessmentSnapshotSchema.nullable(),
  active_goals: z.number().int(),
  disclaimer: z.string(),
});
export type WellnessSummary = z.infer<typeof wellnessSummarySchema>;

export const trendPointSchema = z.object({
  date: z.string(),
  mood: nullableNumber,
  energy: nullableNumber,
  stress: nullableNumber,
  sleep_minutes: nullableNumber,
  sleep_quality: nullableNumber,
});
export type TrendPoint = z.infer<typeof trendPointSchema>;

export const trendsSchema = z.object({
  days: z.number().int(),
  points: z.array(trendPointSchema),
  disclaimer: z.string(),
});
export type Trends = z.infer<typeof trendsSchema>;

export const resourceSchema = z.object({
  id: z.string(),
  title: z.string(),
  summary: z.string(),
  resource_type: z.string(),
  tags: z.array(z.string()),
  duration_minutes: z.number().int().nullable(),
  url: z.string().nullable(),
});
export type Resource = z.infer<typeof resourceSchema>;

export const resourceDetailSchema = resourceSchema.extend({ body: z.string().nullable() });
export type ResourceDetail = z.infer<typeof resourceDetailSchema>;

export const feedbackRatingSchema = z.enum(["helpful", "not_helpful"]);
export type FeedbackRating = z.infer<typeof feedbackRatingSchema>;

export const FEEDBACK_REASONS = [
  "not_relevant",
  "wrong_format",
  "too_long",
  "already_doing_this",
  "not_now",
] as const;
export type FeedbackReason = (typeof FEEDBACK_REASONS)[number];

export const recommendationFeedbackSchema = z.object({
  rating: feedbackRatingSchema,
  reason: z.string().nullable(),
  updated_at: z.string(),
});
export type RecommendationFeedback = z.infer<typeof recommendationFeedbackSchema>;

export const recommendationSchema = z.object({
  id: z.string(),
  title: z.string(),
  rationale: z.string(),
  status: z.string(),
  source: z.string(),
  created_at: z.string(),
  expires_at: z.string().nullable(),
  resource: resourceSchema.nullable(),
  problem_area: z.string().nullable(),
  action: z.string(),
  goal_category: z.string().nullable(),
  feedback: recommendationFeedbackSchema.nullable(),
  disclaimer: z.string(),
});
export type Recommendation = z.infer<typeof recommendationSchema>;

export const recommendationPreferencesSchema = z.object({
  preferred_formats: z.array(z.string()),
  max_minutes: z.number().int().nullable(),
  muted_areas: z.array(z.string()),
  use_indicators: z.boolean(),
  available_formats: z.array(z.string()),
  available_areas: z.array(z.string()),
});
export type RecommendationPreferences = z.infer<typeof recommendationPreferencesSchema>;
export type RecommendationPreferencesPatch = Partial<
  Pick<
    RecommendationPreferences,
    "preferred_formats" | "max_minutes" | "muted_areas" | "use_indicators"
  >
>;

export const appointmentSchema = z.object({
  id: z.string(),
  student_id: z.string(),
  therapist_id: z.string(),
  therapist_name: z.string(),
  starts_at: z.string(),
  ends_at: z.string(),
  mode: z.string(),
  status: z.string(),
  reason: z.string().nullable(),
  can_cancel: z.boolean(),
  can_reschedule: z.boolean(),
  cancelled_at: z.string().nullable(),
  cancel_reason: z.string().nullable(),
  reschedule_count: z.number().int(),
  rescheduled_at: z.string().nullable(),
  /** The delivered session once the therapist starts it: in_progress, completed or abandoned. */
  session_status: z.string().nullable(),
});
export type Appointment = z.infer<typeof appointmentSchema>;

/** The reasons someone can give for cancelling: a fixed list, never free text. */
export const CANCEL_REASONS = [
  { value: "schedule_conflict", label: "Something else came up" },
  { value: "feeling_better", label: "I'm feeling better" },
  { value: "unwell", label: "I'm unwell" },
  { value: "therapist_unavailable", label: "The therapist isn't available" },
  { value: "other", label: "Another reason" },
] as const;
export type CancelReason = (typeof CANCEL_REASONS)[number]["value"];

export function cancelReasonLabel(value: string | null): string | null {
  return CANCEL_REASONS.find((r) => r.value === value)?.label ?? null;
}

export const dashboardSchema = wellnessSummarySchema.extend({
  upcoming_appointment: appointmentSchema.nullable(),
  recent_trends: z.array(trendPointSchema),
  recommendations: z.array(recommendationSchema),
});
export type Dashboard = z.infer<typeof dashboardSchema>;

export const instrumentSchema = z.object({
  id: z.string(),
  version: z.string(),
  title: z.string(),
  intro: z.string(),
  attribution: z.string(),
  disclaimer: z.string(),
  options: z.array(z.object({ value: z.number().int(), label: z.string() })),
  questions: z.array(z.object({ key: z.string(), text: z.string() })),
});
export type Instrument = z.infer<typeof instrumentSchema>;

export const GOAL_CATEGORIES = [
  "sleep",
  "movement",
  "mindfulness",
  "social",
  "academic_balance",
  "nutrition",
  "other",
] as const;
export type GoalCategory = (typeof GOAL_CATEGORIES)[number];
export const GOAL_STATUSES = ["active", "paused", "completed", "abandoned"] as const;
export type GoalStatus = (typeof GOAL_STATUSES)[number];

export const goalSchema = z.object({
  id: z.string(),
  title: z.string(),
  description: z.string().nullable(),
  category: z.string(),
  status: z.string(),
  target_value: nullableNumber,
  current_value: z.number(),
  unit: z.string().nullable(),
  progress_percent: z.number().int().nullable(),
  start_date: z.string(),
  target_date: z.string().nullable(),
  completed_at: z.string().nullable(),
});
export type Goal = z.infer<typeof goalSchema>;

export const therapistSchema = z.object({
  id: z.string(),
  full_name: z.string(),
  specialties: z.array(z.string()),
  languages: z.array(z.string()),
  accepting_new_students: z.boolean(),
  next_available_at: z.string().nullable(),
  on_my_care_team: z.boolean(),
});
export type Therapist = z.infer<typeof therapistSchema>;

export const therapistDetailSchema = therapistSchema.extend({ bio: z.string().nullable() });
export type TherapistDetail = z.infer<typeof therapistDetailSchema>;

export const slotSchema = z.object({
  id: z.string(),
  starts_at: z.string(),
  ends_at: z.string(),
  mode: z.string(),
});
export type Slot = z.infer<typeof slotSchema>;

export const conversationSchema = z.object({
  other_id: z.string(),
  other_name: z.string(),
  active: z.boolean(),
  last_message_at: z.string().nullable(),
  last_message_preview: z.string().nullable(),
  unread_count: z.number().int(),
});
export type Conversation = z.infer<typeof conversationSchema>;

export const messageSchema = z.object({
  id: z.string(),
  sender_id: z.string(),
  mine: z.boolean(),
  body: z.string(),
  created_at: z.string(),
  read_at: z.string().nullable(),
});
export type Message = z.infer<typeof messageSchema>;

export const sentMessageSchema = z.object({
  message: messageSchema,
  support: supportInfoSchema.nullable(),
});

export const consentSchema = z.object({
  scope: z.string(),
  title: z.string(),
  description: z.string(),
  required: z.boolean(),
  granted: z.boolean(),
  granted_at: z.string().nullable(),
  policy_version: z.string().nullable(),
});
export type Consent = z.infer<typeof consentSchema>;

export const accessEventSchema = z.object({
  occurred_at: z.string(),
  actor_role: z.string().nullable(),
  action: z.string(),
  resource_type: z.string().nullable(),
});
export type AccessEvent = z.infer<typeof accessEventSchema>;

export const supportRequestSchema = z.object({
  id: z.string(),
  status: z.string(),
  already_open: z.boolean(),
  reaches_care_team: z.boolean(),
  created_at: z.string(),
});
export type SupportRequest = z.infer<typeof supportRequestSchema>;

export const crisisContactSchema = z.object({
  id: z.string(),
  label: z.string(),
  kind: z.string(),
  phone: z.string().nullable(),
  url: z.string().nullable(),
  description: z.string().nullable(),
  hours: z.string().nullable(),
});
export type CrisisContact = z.infer<typeof crisisContactSchema>;

export const readSchema = z.object({ marked_read: z.number().int() });

export const aiConversationSchema = z.object({
  id: z.string(),
  status: z.string(),
  started_at: z.string(),
  ended_at: z.string().nullable(),
});
export type AiConversation = z.infer<typeof aiConversationSchema>;
