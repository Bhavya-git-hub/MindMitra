/** Typed wrappers for the therapist-portal endpoints. Components never call `fetch` directly. */
import { z } from "zod";

import type { ApiClient } from "./client";
import { browserTimeZone } from "./student-api";
import type { CancelReason } from "./student-schemas";
import {
  alertSchema,
  appointmentSchema,
  assessmentSchema,
  caseloadStudentSchema,
  dashboardSchema,
  followUpSchema,
  madeRecommendationSchema,
  noteSchema,
  profileSchema,
  sessionSchema,
  slotSchema,
  studentProfileSchema,
  therapistAnalyticsSchema,
  trendsSchema,
  type FollowUpKind,
} from "./therapist-schemas";
import { qs } from "./query-string";
import type { WindowWeeks } from "./teacher-schemas";

export interface ProfilePatch {
  bio?: string;
  specialties?: string[];
  languages?: string[];
  accepting_new_students?: boolean;
  max_caseload?: number;
}

export interface VerificationInput {
  licence_number: string;
  licence_body?: string;
  licence_expires_on?: string;
}

export interface AvailabilityInput {
  starts_at: string;
  ends_at: string;
  mode: "video" | "in_person" | "phone";
  repeat_weeks: number;
}

export interface FollowUpInput {
  student_id: string;
  kind: FollowUpKind;
  due_on: string;
  note?: string;
  session_id?: string;
}

export interface FollowUpPatch {
  status?: "open" | "done" | "cancelled";
  due_on?: string;
  note?: string;
}

export type AppointmentScope = "requests" | "upcoming" | "past" | "all";

export function createTherapistApi(client: ApiClient, timeZone: () => string = browserTimeZone) {
  const tz = () => ({ tz: timeZone() });
  const list = <T>(schema: z.ZodType<T>) => z.array(schema);

  return {
    dashboard: () => client.request(`/therapist/dashboard${qs(tz())}`, { schema: dashboardSchema }),

    /** Counts and averages over this therapist's own caseload and work, in finished weeks. */
    analytics: (weeks: WindowWeeks) =>
      client.request(`/therapist/analytics${qs({ ...tz(), weeks })}`, {
        schema: therapistAnalyticsSchema,
      }),

    profile: () => client.request("/therapist/profile", { schema: profileSchema }),
    updateProfile: (patch: ProfilePatch) =>
      client.request("/therapist/profile", { method: "PATCH", body: patch, schema: profileSchema }),
    submitVerification: (input: VerificationInput) =>
      client.request("/therapist/verification", {
        method: "POST",
        body: input,
        schema: profileSchema,
      }),

    availability: (from: string, to: string) =>
      client.request(`/therapist/availability${qs({ from, to })}`, { schema: list(slotSchema) }),
    addAvailability: (input: AvailabilityInput) =>
      client.request("/therapist/availability", {
        method: "POST",
        body: input,
        schema: list(slotSchema),
      }),
    removeAvailability: (id: string) =>
      client.request(`/therapist/availability/${id}`, { method: "DELETE" }),

    appointments: (scope: AppointmentScope = "all", limit = 100) =>
      client.request(`/therapist/appointments${qs({ scope, limit })}`, {
        schema: list(appointmentSchema),
      }),
    /** Confirm, decline (cancel) or close an appointment. */
    setAppointmentStatus: (
      id: string,
      status: "confirmed" | "cancelled" | "no_show",
      cancelReason?: CancelReason,
    ) =>
      client.request(`/appointments/${id}`, {
        method: "PATCH",
        body:
          status === "cancelled" && cancelReason
            ? { status, cancel_reason: cancelReason }
            : { status },
      }),
    /** Move to another of this therapist's open times; the student is told. */
    rescheduleAppointment: (id: string, availability_id: string) =>
      client.request(`/therapist/appointments/${id}/reschedule`, {
        method: "POST",
        body: { availability_id },
        schema: appointmentSchema,
      }),

    students: () => client.request("/therapist/students", { schema: list(caseloadStudentSchema) }),
    student: (id: string) =>
      client.request(`/therapist/students/${id}`, { schema: studentProfileSchema }),
    studentTrends: (id: string, days: number) =>
      client.request(`/therapist/students/${id}/trends${qs({ ...tz(), days })}`, {
        schema: trendsSchema,
      }),
    studentAssessments: (id: string) =>
      client.request(`/therapist/students/${id}/assessments`, { schema: list(assessmentSchema) }),
    studentRecommendations: (id: string) =>
      client.request(`/therapist/students/${id}/recommendations`, {
        schema: list(madeRecommendationSchema),
      }),
    recommend: (id: string, input: { title: string; rationale: string; resource_id?: string }) =>
      client.request(`/therapist/students/${id}/recommendations`, {
        method: "POST",
        body: input,
        schema: madeRecommendationSchema,
      }),

    sessions: (status?: string) =>
      client.request(`/therapist/sessions${qs({ status })}`, { schema: list(sessionSchema) }),
    startSession: (appointmentId: string) =>
      client.request(`/therapist/appointments/${appointmentId}/session`, {
        method: "POST",
        schema: sessionSchema,
      }),
    finishSession: (id: string, status: "completed" | "abandoned") =>
      client.request(`/therapist/sessions/${id}`, {
        method: "PATCH",
        body: { status },
        schema: sessionSchema,
      }),
    note: (sessionId: string, version?: number) =>
      client.request(`/therapist/sessions/${sessionId}/note${qs({ version })}`, {
        schema: noteSchema,
      }),
    saveNote: (sessionId: string, body: string) =>
      client.request(`/therapist/sessions/${sessionId}/note`, {
        method: "PUT",
        body: { body },
        schema: noteSchema,
      }),

    alerts: (closed = false) =>
      client.request(`/therapist/alerts${qs({ closed: closed || undefined })}`, {
        schema: list(alertSchema),
      }),
    actOnAlert: (id: string, action: "acknowledge" | "start" | "resolve", outcome?: string) =>
      client.request(`/therapist/alerts/${id}`, {
        method: "PATCH",
        body: { action, outcome },
        schema: alertSchema,
      }),

    followUps: (status?: "open" | "done" | "cancelled", studentId?: string) =>
      client.request(`/therapist/follow-ups${qs({ ...tz(), status, student_id: studentId })}`, {
        schema: list(followUpSchema),
      }),
    createFollowUp: (input: FollowUpInput) =>
      client.request(`/therapist/follow-ups${qs(tz())}`, {
        method: "POST",
        body: input,
        schema: followUpSchema,
      }),
    updateFollowUp: (id: string, patch: FollowUpPatch) =>
      client.request(`/therapist/follow-ups/${id}${qs(tz())}`, {
        method: "PATCH",
        body: patch,
        schema: followUpSchema,
      }),
  };
}

export type TherapistApi = ReturnType<typeof createTherapistApi>;
