/** Synthetic API payloads for the student-portal tests (no real people or data). */
import type {
  Appointment,
  Consent,
  Conversation,
  CrisisContact,
  Dashboard,
  Goal,
  Instrument,
  Message,
  Recommendation,
  Resource,
  Safety,
  Slot,
  Therapist,
  TrendPoint,
  WellnessAnalytics,
} from "@/lib/api/student-schemas";

import { json, makeSession, type TestSession } from "./render";

type Handlers = Parameters<typeof makeSession>[0];

/** A signed-in student whose API answers `handlers` (and nothing else). */
export function studentSession(handlers: Handlers = {}): TestSession {
  return makeSession(handlers, { signedInAs: "student" });
}

export const THERAPIST_ID = "0192a000-0000-7000-8000-000000000001";
export const SLOT_ID = "0192a000-0000-7000-8000-0000000000a1";

export const day = (offset: number): string => {
  const d = new Date(Date.UTC(2026, 9, 10 + offset));
  return d.toISOString().slice(0, 10);
};

export const trendPoint = (offset: number, extra: Partial<TrendPoint> = {}): TrendPoint => ({
  date: day(offset),
  mood: null,
  energy: null,
  stress: null,
  sleep_minutes: null,
  sleep_quality: null,
  ...extra,
});

export const recommendation = (extra: Partial<Recommendation> = {}): Recommendation => ({
  id: "rec-1",
  title: "Try a short breathing exercise",
  rationale: "You mentioned feeling stressed this week.",
  status: "pending",
  source: "rule",
  created_at: "2026-10-09T08:00:00Z",
  expires_at: null,
  resource: {
    id: "res-1",
    title: "Box breathing in four steps",
    summary: "A calming exercise.",
    resource_type: "exercise",
    tags: ["stress"],
    duration_minutes: 5,
    url: null,
  },
  problem_area: "stress",
  action: "resource",
  goal_category: null,
  feedback: null,
  disclaimer: "Not medical advice.",
  ...extra,
});

export const appointment = (extra: Partial<Appointment> = {}): Appointment => ({
  id: "appt-1",
  student_id: "user-1",
  therapist_id: THERAPIST_ID,
  therapist_name: "Dr. Priya Nair",
  starts_at: "2026-10-14T10:00:00Z",
  ends_at: "2026-10-14T10:50:00Z",
  mode: "video",
  status: "confirmed",
  reason: null,
  can_cancel: true,
  can_reschedule: true,
  cancelled_at: null,
  cancel_reason: null,
  reschedule_count: 0,
  rescheduled_at: null,
  session_status: null,
  ...extra,
});

export const dashboard = (extra: Partial<Dashboard> = {}): Dashboard => ({
  date: day(0),
  check_in: {
    done_today: false,
    streak_days: 0,
    check_ins_last_7d: 0,
    days_since_last: null,
    emotions_today: [],
  },
  mood: { today: null, average_7d: null, indicator: null, direction: null },
  stress: { today: null, average_7d: null, indicator: null, direction: null },
  sleep: {
    last_night_minutes: null,
    last_night_quality: null,
    average_minutes_7d: null,
    indicator: null,
    direction: null,
  },
  wellbeing: null,
  active_goals: 0,
  disclaimer: "These are self-reported numbers, not a diagnosis.",
  upcoming_appointment: null,
  recent_trends: [],
  recommendations: [],
  ...extra,
});

export const filledDashboard = (): Dashboard =>
  dashboard({
    check_in: {
      done_today: true,
      streak_days: 3,
      check_ins_last_7d: 5,
      days_since_last: 0,
      emotions_today: ["calm", "hopeful"],
    },
    mood: {
      today: 4,
      average_7d: 3.6,
      indicator: { key: "good", label: "Feeling good" },
      direction: "up",
    },
    stress: {
      today: 2,
      average_7d: 2.8,
      indicator: { key: "calm", label: "Mostly calm" },
      direction: "down",
    },
    sleep: {
      last_night_minutes: 450,
      last_night_quality: 4,
      average_minutes_7d: 420,
      indicator: { key: "steady", label: "Resting well" },
      direction: "steady",
    },
    wellbeing: {
      id: "as-1",
      score: 17,
      max_score: 25,
      percent: 68,
      band: { key: "mixed", label: "Mixed", message: "Some days are better than others." },
      completed_at: "2026-10-08T09:00:00Z",
    },
    upcoming_appointment: appointment(),
    recent_trends: [
      trendPoint(-2, { mood: 3, stress: 3 }),
      trendPoint(-1, { mood: 4, stress: 2 }),
      trendPoint(0, { mood: 4, stress: 2 }),
    ],
    recommendations: [recommendation()],
  });

export const therapist = (extra: Partial<Therapist> = {}): Therapist => ({
  id: THERAPIST_ID,
  full_name: "Dr. Priya Nair",
  specialties: ["Anxiety", "Study stress"],
  languages: ["English", "Hindi"],
  accepting_new_students: true,
  next_available_at: "2026-10-14T10:00:00Z",
  on_my_care_team: false,
  ...extra,
});

export const slot = (extra: Partial<Slot> = {}): Slot => ({
  id: SLOT_ID,
  starts_at: "2026-10-14T10:00:00Z",
  ends_at: "2026-10-14T10:50:00Z",
  mode: "video",
  ...extra,
});

export const goal = (extra: Partial<Goal> = {}): Goal => ({
  id: "goal-1",
  title: "Wind down before midnight",
  description: null,
  category: "sleep",
  status: "active",
  target_value: 5,
  current_value: 2,
  unit: "nights",
  progress_percent: 40,
  start_date: day(-3),
  target_date: null,
  completed_at: null,
  ...extra,
});

export const consent = (extra: Partial<Consent> = {}): Consent => ({
  scope: "share_mood_with_care_team",
  title: "Share my mood check-ins with my therapist",
  description: "Lets a therapist on your care team see your mood scores.",
  required: false,
  granted: false,
  granted_at: null,
  policy_version: null,
  ...extra,
});

export const contact = (extra: Partial<CrisisContact> = {}): CrisisContact => ({
  id: "c-1",
  label: "Demo helpline",
  kind: "helpline",
  phone: "+91 (0) 11 5550 0100",
  url: "https://example.org/help",
  description: "Synthetic demo entry.",
  hours: "24 hours",
  ...extra,
});

/** A HIGH concern from a check-in note, where the student allowed safety checks. */
export const safety = (extra: Partial<Safety> = {}): Safety => ({
  level: "high",
  about_someone_else: false,
  emergency_first: false,
  offer_outreach: false,
  guidance: {
    title: "You don't have to go through this alone",
    message: "What you wrote sounds really hard. Talking to someone today can help.",
    steps: ["Reach out to someone you trust today.", "Contact one of the people below."],
  },
  resources: [
    {
      id: null,
      label: "Local emergency services",
      kind: "emergency",
      phone: null,
      url: null,
      description: "Call your local emergency number.",
      hours: "24 hours",
    },
    {
      id: "c-1",
      label: "Demo helpline",
      kind: "helpline",
      phone: "+91 (0) 11 5550 0100",
      url: null,
      description: "Synthetic demo entry.",
      hours: "24 hours",
    },
  ],
  counselling: {
    has_care_team: true,
    message_path: "/student/messages",
    booking_path: "/student/therapists",
  },
  escalation: { status: "requested", basis: "consent", care_team_notified: true },
  recommendations_paused: true,
  paused_until: "2026-10-13T08:00:00Z",
  disclaimer: "MindMitra is not an emergency service.",
  ...extra,
});

export const conversation = (extra: Partial<Conversation> = {}): Conversation => ({
  other_id: THERAPIST_ID,
  other_name: "Dr. Priya Nair",
  active: true,
  last_message_at: "2026-10-09T10:00:00Z",
  last_message_preview: "See you on Tuesday.",
  unread_count: 0,
  ...extra,
});

export const message = (extra: Partial<Message> = {}): Message => ({
  id: "m-1",
  sender_id: THERAPIST_ID,
  mine: false,
  body: "See you on Tuesday.",
  created_at: "2026-10-09T10:00:00Z",
  read_at: null,
  ...extra,
});

export const resource = (extra: Partial<Resource> = {}): Resource => ({
  id: "res-1",
  title: "Box breathing in four steps",
  summary: "A calming exercise.",
  resource_type: "exercise",
  tags: ["stress"],
  duration_minutes: 5,
  url: null,
  ...extra,
});

export const instrument = (): Instrument => ({
  id: "who5",
  version: "1",
  title: "Wellbeing check",
  intro: "Over the last two weeks…",
  attribution: "Based on the WHO-5 Well-Being Index.",
  disclaimer: "This is not a diagnosis.",
  options: [
    { value: 0, label: "At no time" },
    { value: 3, label: "More than half the time" },
    { value: 5, label: "All of the time" },
  ],
  questions: [
    { key: "q1", text: "I have felt cheerful" },
    { key: "q2", text: "I have felt calm" },
  ],
});

export { json };

export const analyticsWeek = (
  offsetWeeks: number,
  extra: Partial<WellnessAnalytics["weeks"][number]> = {},
): WellnessAnalytics["weeks"][number] => ({
  week_start: day(offsetWeeks * 7 - 5), // `day(0)` is Saturday 10 Oct 2026, so -5 is its Monday
  wellness_index: null,
  mood_avg: null,
  stress_avg: null,
  sleep_quality_avg: null,
  sleep_hours_avg: null,
  days_reported: 0,
  partial: false,
  ...extra,
});

/** An analytics response with nothing in it, as a brand-new student would get. */
export const emptyAnalytics = (): WellnessAnalytics => ({
  weeks: [-3, -2, -1, 0].map((n) => analyticsWeek(n, { partial: n === 0 })),
  wellbeing_checks: [],
  goals: {
    active: 0,
    completed: 0,
    other: 0,
    average_progress_percent: null,
    by_category: [],
    completed_by_week: [-3, -2, -1, 0].map((n) => ({
      week_start: analyticsWeek(n).week_start,
      completed: 0,
    })),
  },
  disclaimer: "These figures describe what you reported. They are not a diagnosis.",
});
