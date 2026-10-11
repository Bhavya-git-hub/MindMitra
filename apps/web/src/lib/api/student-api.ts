/** Typed wrappers for the student-portal endpoints. Components never call `fetch` directly. */
import { z } from "zod";

import type { ApiClient } from "./client";
import {
  accessEventSchema,
  aiConversationSchema,
  appointmentSchema,
  assessmentSnapshotSchema,
  checkInResultSchema,
  consentSchema,
  conversationSchema,
  crisisContactSchema,
  dashboardSchema,
  goalSchema,
  instrumentSchema,
  messageSchema,
  moodEntrySchema,
  readSchema,
  recommendationPreferencesSchema,
  recommendationSchema,
  resourceDetailSchema,
  resourceSchema,
  safetyStatusSchema,
  sentMessageSchema,
  sleepEntrySchema,
  slotSchema,
  stressEntrySchema,
  supportRequestSchema,
  therapistDetailSchema,
  therapistSchema,
  trendsSchema,
  wellnessAnalyticsSchema,
  wellnessSummarySchema,
  type CancelReason,
  type FeedbackRating,
  type FeedbackReason,
  type GoalCategory,
  type GoalStatus,
  type RecommendationPreferencesPatch,
} from "./student-schemas";
import { qs } from "./query-string";

/** How many past suggestions one history page holds. */
export const RECOMMENDATION_PAGE = 50;

export interface SleepInput {
  bedtime: string;
  wake_time: string;
  quality: number;
}

export interface CheckInInput {
  mood_score: number;
  energy_level?: number;
  emotions?: string[];
  note?: string;
  stress_level?: number;
  stressors?: string[];
  sleep?: SleepInput;
}

export interface GoalInput {
  title: string;
  category: GoalCategory;
  description?: string;
  target_value?: number;
  unit?: string;
  target_date?: string;
}

export interface GoalPatch {
  title?: string;
  description?: string | null;
  current_value?: number;
  target_value?: number | null;
  target_date?: string | null;
  status?: GoalStatus;
}

/** The viewer's IANA time zone, so "today" means the student's today. */
export function browserTimeZone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
  } catch {
    return "UTC";
  }
}

export function createStudentApi(client: ApiClient, timeZone: () => string = browserTimeZone) {
  const tz = () => ({ tz: timeZone() });
  const list = <T>(schema: z.ZodType<T>) => z.array(schema);

  return {
    dashboard: () => client.request(`/me/dashboard${qs(tz())}`, { schema: dashboardSchema }),
    summary: () =>
      client.request(`/me/wellness/summary${qs(tz())}`, { schema: wellnessSummarySchema }),
    trends: (days: number) =>
      client.request(`/me/wellness/trends${qs({ ...tz(), days })}`, { schema: trendsSchema }),
    /** Weekly self-reported figures, recent wellbeing checks and goal progress (4 to 12 weeks). */
    wellnessAnalytics: (weeks: number) =>
      client.request(`/me/wellness/analytics${qs({ ...tz(), weeks })}`, {
        schema: wellnessAnalyticsSchema,
      }),

    checkIn: (input: CheckInInput) =>
      client.request(`/me/check-ins${qs(tz())}`, {
        method: "POST",
        body: input,
        schema: checkInResultSchema,
      }),
    moodEntries: (days?: number, limit = 100) =>
      client.request(`/me/wellness/mood-entries${qs({ ...tz(), days, limit })}`, {
        schema: list(moodEntrySchema),
      }),
    stressEntries: (days?: number, limit = 100) =>
      client.request(`/me/wellness/stress-entries${qs({ ...tz(), days, limit })}`, {
        schema: list(stressEntrySchema),
      }),
    logStress: (stress_level: number, stressors: string[]) =>
      client.request(`/me/wellness/stress-entries${qs(tz())}`, {
        method: "POST",
        body: { stress_level, stressors },
        schema: stressEntrySchema,
      }),
    sleepEntries: (days?: number, limit = 100) =>
      client.request(`/me/wellness/sleep-entries${qs({ ...tz(), days, limit })}`, {
        schema: list(sleepEntrySchema),
      }),
    logSleep: (input: SleepInput) =>
      client.request(`/me/wellness/sleep-entries${qs(tz())}`, {
        method: "PUT",
        body: input,
        schema: sleepEntrySchema,
      }),

    assessmentInstrument: () =>
      client.request("/me/wellness/assessment", { schema: instrumentSchema }),
    assessments: () =>
      client.request("/me/wellness/assessments", { schema: list(assessmentSnapshotSchema) }),
    submitAssessment: (responses: Record<string, number>) =>
      client.request(`/me/wellness/assessments${qs(tz())}`, {
        method: "POST",
        body: { responses },
        schema: assessmentSnapshotSchema,
      }),

    goals: (status?: GoalStatus) =>
      client.request(`/me/goals${qs({ status })}`, { schema: list(goalSchema) }),
    createGoal: (input: GoalInput) =>
      client.request("/me/goals", { method: "POST", body: input, schema: goalSchema }),
    updateGoal: (id: string, patch: GoalPatch) =>
      client.request(`/me/goals/${id}`, { method: "PATCH", body: patch, schema: goalSchema }),

    recommendations: (includeClosed = false) =>
      client.request(`/me/recommendations${qs({ include_closed: includeClosed || undefined })}`, {
        schema: list(recommendationSchema),
      }),
    refreshRecommendations: () =>
      client.request(`/me/recommendations/refresh${qs(tz())}`, {
        method: "POST",
        schema: list(recommendationSchema),
      }),
    respondToRecommendation: (id: string, status: "viewed" | "dismissed" | "completed") =>
      client.request(`/me/recommendations/${id}`, {
        method: "PATCH",
        body: { status },
        schema: recommendationSchema,
      }),
    recommendationHistory: (offset = 0) =>
      client.request(
        `/me/recommendations/history${qs({ limit: RECOMMENDATION_PAGE, offset: offset || undefined })}`,
        { schema: list(recommendationSchema) },
      ),
    rateRecommendation: (id: string, rating: FeedbackRating, reason?: FeedbackReason) =>
      client.request(`/me/recommendations/${id}/feedback`, {
        method: "PUT",
        body: { rating, reason: reason ?? null },
        schema: recommendationSchema,
      }),
    clearRecommendationRating: (id: string) =>
      client.request(`/me/recommendations/${id}/feedback`, {
        method: "DELETE",
        schema: recommendationSchema,
      }),
    recommendationPreferences: () =>
      client.request("/me/recommendations/preferences", {
        schema: recommendationPreferencesSchema,
      }),
    updateRecommendationPreferences: (patch: RecommendationPreferencesPatch) =>
      client.request("/me/recommendations/preferences", {
        method: "PATCH",
        body: patch,
        schema: recommendationPreferencesSchema,
      }),

    resources: (filter: { type?: string; tag?: string; q?: string } = {}) =>
      client.request(
        `/resources${qs({ resource_type: filter.type, tag: filter.tag, q: filter.q })}`,
        { schema: list(resourceSchema) },
      ),
    resource: (id: string) => client.request(`/resources/${id}`, { schema: resourceDetailSchema }),

    therapists: (filter: { specialty?: string; language?: string; acceptingOnly?: boolean } = {}) =>
      client.request(
        `/therapists${qs({
          specialty: filter.specialty,
          language: filter.language,
          accepting_only: filter.acceptingOnly || undefined,
        })}`,
        { schema: list(therapistSchema) },
      ),
    therapist: (id: string) =>
      client.request(`/therapists/${id}`, { schema: therapistDetailSchema }),
    therapistSlots: (id: string) =>
      client.request(`/therapists/${id}/slots`, { schema: list(slotSchema) }),

    appointments: (upcoming?: boolean) =>
      client.request(`/me/appointments${qs({ upcoming })}`, { schema: list(appointmentSchema) }),
    bookAppointment: (availability_id: string, reason?: string) =>
      client.request("/me/appointments", {
        method: "POST",
        body: { availability_id, reason: reason || undefined },
        schema: appointmentSchema,
      }),
    cancelAppointment: (id: string, reason?: CancelReason) =>
      client.request(`/me/appointments/${id}`, {
        method: "PATCH",
        body: reason ? { status: "cancelled", reason } : { status: "cancelled" },
        schema: appointmentSchema,
      }),
    /** Move to another of the same therapist's open times; it goes back to "requested". */
    rescheduleAppointment: (id: string, availability_id: string) =>
      client.request(`/me/appointments/${id}/reschedule`, {
        method: "POST",
        body: { availability_id },
        schema: appointmentSchema,
      }),

    conversations: () => client.request("/me/conversations", { schema: list(conversationSchema) }),
    messages: (otherId: string) =>
      client.request(`/me/conversations/${otherId}/messages`, { schema: list(messageSchema) }),
    sendMessage: (otherId: string, body: string, clientMsgId: string) =>
      client.request(`/me/conversations/${otherId}/messages`, {
        method: "POST",
        body: { body, client_msg_id: clientMsgId },
        schema: sentMessageSchema,
      }),
    markConversationRead: (otherId: string) =>
      client.request(`/me/conversations/${otherId}/read`, { method: "POST", schema: readSchema }),

    consents: () => client.request("/me/consents", { schema: list(consentSchema) }),
    setConsent: (scope: string, granted: boolean) =>
      client.request(`/me/consents/${scope}`, {
        method: "PUT",
        body: { granted },
        schema: consentSchema,
      }),
    accessHistory: () =>
      client.request("/me/privacy/access-history", { schema: list(accessEventSchema) }),
    /** The whole export as text, for the browser to save (the API sends it as JSON). */
    exportData: () =>
      client.request("/me/privacy/export", { schema: z.record(z.string(), z.unknown()) }),

    requestSupport: (message?: string) =>
      client.request("/me/support-requests", {
        method: "POST",
        body: { message: message || undefined },
        schema: supportRequestSchema,
      }),
    crisisContacts: () =>
      client.request("/me/safety/resources", { schema: list(crisisContactSchema) }),
    /** Whether normal suggestions are paused for safety, and the support to show meanwhile. */
    safetyStatus: () => client.request("/me/safety/status", { schema: safetyStatusSchema }),

    aiConversations: () =>
      client.request("/me/ai-conversations", { schema: list(aiConversationSchema) }),
  };
}

export type StudentApi = ReturnType<typeof createStudentApi>;
