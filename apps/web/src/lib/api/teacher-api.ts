/** Typed wrappers for the teacher-portal endpoints. Components never call `fetch` directly. */
import { z } from "zod";

import type { ApiClient } from "./client";
import { qs } from "./query-string";
import { resourceDetailSchema, resourceSchema } from "./student-schemas";
import {
  classAnalyticsSchema,
  classSchema,
  courseOptionSchema,
  dashboardSchema,
  departmentAnalyticsSchema,
  referralDetailSchema,
  referralSchema,
  reportSchema,
  rosterSchema,
  supportRequestSchema,
  triageReferralSchema,
  type WindowWeeks,
} from "./teacher-schemas";

export interface ReferralInput {
  student_id: string;
  course_id: string;
  category: string;
  urgency: string;
  note?: string;
}

export interface SupportRequestInput {
  course_id: string;
  teacher_id: string;
  topic: string;
  message?: string;
}

/** A group is a class or the teacher's own department. */
export type GroupRef = { kind: "class" | "department"; id: string };

const groupPath = ({ kind, id }: GroupRef) =>
  kind === "class" ? `/teacher/classes/${id}` : `/teacher/departments/${id}`;

export function createTeacherApi(client: ApiClient) {
  const list = <T>(schema: z.ZodType<T>) => z.array(schema);

  return {
    dashboard: () => client.request("/teacher/dashboard", { schema: dashboardSchema }),

    classes: () => client.request("/teacher/classes", { schema: list(classSchema) }),
    class: (id: string) => client.request(`/teacher/classes/${id}`, { schema: classSchema }),
    roster: (id: string) =>
      client.request(`/teacher/classes/${id}/students`, { schema: list(rosterSchema) }),

    classAnalytics: (id: string, weeks: WindowWeeks) =>
      client.request(`/teacher/classes/${id}/analytics${qs({ weeks })}`, {
        schema: classAnalyticsSchema,
      }),
    departmentAnalytics: (id: string, weeks: WindowWeeks) =>
      client.request(`/teacher/departments/${id}/analytics${qs({ weeks })}`, {
        schema: departmentAnalyticsSchema,
      }),
    report: (group: GroupRef, weeks: WindowWeeks) =>
      client.request(`${groupPath(group)}/report${qs({ weeks })}`, { schema: reportSchema }),
    reportCsv: (group: GroupRef, weeks: WindowWeeks) =>
      client.request<string>(`${groupPath(group)}/report.csv${qs({ weeks })}`, {
        responseType: "text",
      }),

    referrals: () => client.request("/teacher/referrals", { schema: list(referralSchema) }),
    referral: (id: string) =>
      client.request(`/teacher/referrals/${id}`, { schema: referralDetailSchema }),
    createReferral: (input: ReferralInput) =>
      client.request("/teacher/referrals", {
        method: "POST",
        body: input,
        schema: referralDetailSchema,
      }),

    supportRequests: (status?: "open" | "acknowledged" | "closed") =>
      client.request(`/teacher/support-requests${qs({ status })}`, {
        schema: list(supportRequestSchema),
      }),
    acknowledgeRequest: (id: string) =>
      client.request(`/teacher/support-requests/${id}/acknowledge`, {
        method: "POST",
        schema: supportRequestSchema,
      }),
    closeRequest: (id: string) =>
      client.request(`/teacher/support-requests/${id}/close`, {
        method: "POST",
        schema: supportRequestSchema,
      }),

    resources: (filter: { type?: string; tag?: string; q?: string } = {}) =>
      client.request(
        `/teacher/resources${qs({ resource_type: filter.type, tag: filter.tag, q: filter.q })}`,
        { schema: list(resourceSchema) },
      ),
    resource: (id: string) =>
      client.request(`/teacher/resources/${id}`, { schema: resourceDetailSchema }),

    // therapist side: referrals from teachers
    triageQueue: (status?: "received" | "in_progress" | "closed") =>
      client.request(`/therapist/referrals${qs({ status })}`, {
        schema: list(triageReferralSchema),
      }),
    claimReferral: (id: string) =>
      client.request(`/therapist/referrals/${id}/claim`, {
        method: "POST",
        schema: triageReferralSchema,
      }),
    closeReferral: (id: string, outcome: string) =>
      client.request(`/therapist/referrals/${id}/close`, {
        method: "POST",
        body: { outcome },
        schema: triageReferralSchema,
      }),

    // student side: asking one of my own teachers for help
    myCourses: () =>
      client.request("/me/teacher-support/options", { schema: list(courseOptionSchema) }),
    myRequests: () => client.request("/me/teacher-support", { schema: list(supportRequestSchema) }),
    askTeacher: (input: SupportRequestInput) =>
      client.request("/me/teacher-support", {
        method: "POST",
        body: input,
        schema: supportRequestSchema,
      }),
    withdrawRequest: (id: string) =>
      client.request(`/me/teacher-support/${id}/withdraw`, {
        method: "POST",
        schema: supportRequestSchema,
      }),
  };
}

export type TeacherApi = ReturnType<typeof createTeacherApi>;
