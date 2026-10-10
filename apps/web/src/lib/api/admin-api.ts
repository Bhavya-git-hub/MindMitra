/** Typed wrappers for the administrator endpoints. Components never call `fetch` directly. */
import { z } from "zod";

import {
  adminResourceSchema,
  auditEventSchema,
  chainStatusSchema,
  courseDetailSchema,
  courseSchema,
  crisisContactSchema,
  dashboardSchema,
  departmentSchema,
  institutionSchema,
  notificationSettingsSchema,
  oversightSchema,
  pageOf,
  platformAnalyticsSchema,
  reviewSchema,
  safetySettingsSchema,
  type SafetySettings,
  studentDetailSchema,
  studentSchema,
  teacherAccountSchema,
  therapistAccountSchema,
  userSchema,
} from "./admin-schemas";
import type { ApiClient } from "./client";
import { qs } from "./query-string";
import type { WindowWeeks } from "./teacher-schemas";

export interface PageQuery {
  q?: string;
  status?: string;
  limit?: number;
  offset?: number;
}

export interface NewUserInput {
  email: string;
  full_name: string;
  role: string;
  department_code?: string;
  student_number?: string;
  enrollment_year?: number;
  year_of_study?: number;
  employee_number?: string;
  licence_number?: string;
}

export interface ResourceInput {
  title: string;
  summary: string;
  resource_type: string;
  body?: string | null;
  url?: string | null;
  tags: string[];
  language: string;
  duration_minutes?: number | null;
  publish?: boolean;
}

export interface ContactInput {
  label: string;
  kind: string;
  phone?: string | null;
  url?: string | null;
  description?: string | null;
  hours?: string | null;
  sort_order?: number;
  is_active?: boolean;
}

export interface AuditFilter {
  action?: string;
  outcome?: string;
  actor_id?: string;
  resource_type?: string;
  since?: string;
  until?: string;
}

export function createAdminApi(client: ApiClient) {
  const none = { method: "DELETE" as const };

  return {
    dashboard: () => client.request("/admin/dashboard", { schema: dashboardSchema }),

    // accounts
    users: (query: PageQuery & { role?: string }) =>
      client.request(`/admin/users${qs({ ...query })}`, { schema: pageOf(userSchema) }),
    createUser: (input: NewUserInput) =>
      client.request("/admin/users", { method: "POST", body: input, schema: userSchema }),
    setUserStatus: (id: string, status: string) =>
      client.request(`/admin/users/${id}`, {
        method: "PATCH",
        body: { status },
        schema: userSchema,
      }),
    resendInvite: (id: string) =>
      client.request(`/admin/users/${id}/resend-invite`, { method: "POST" }),
    signOutEverywhere: (id: string) =>
      client.request(`/admin/users/${id}/sign-out`, { method: "POST" }),

    students: (query: PageQuery & { department_id?: string }) =>
      client.request(`/admin/students${qs({ ...query })}`, { schema: pageOf(studentSchema) }),
    student: (id: string) =>
      client.request(`/admin/students/${id}`, { schema: studentDetailSchema }),
    updateStudent: (
      id: string,
      patch: {
        department_id?: string;
        year_of_study?: number;
        enrollment_year?: number;
        student_number?: string;
      },
    ) =>
      client.request(`/admin/students/${id}`, {
        method: "PATCH",
        body: patch,
        schema: studentSchema,
      }),
    teachers: (query: PageQuery & { department_id?: string }) =>
      client.request(`/admin/teachers${qs({ ...query })}`, {
        schema: pageOf(teacherAccountSchema),
      }),
    updateTeacher: (
      id: string,
      patch: { department_id?: string; title?: string; employee_number?: string },
    ) =>
      client.request(`/admin/teachers/${id}`, {
        method: "PATCH",
        body: patch,
        schema: teacherAccountSchema,
      }),
    therapists: (query: PageQuery) =>
      client.request(`/admin/therapist-accounts${qs({ ...query })}`, {
        schema: pageOf(therapistAccountSchema),
      }),
    updateTherapist: (id: string, patch: { max_caseload?: number; licence_number?: string }) =>
      client.request(`/admin/therapist-accounts/${id}`, {
        method: "PATCH",
        body: patch,
        schema: therapistAccountSchema,
      }),

    // verification
    verificationQueue: (status?: string) =>
      client.request(`/admin/therapists${qs({ status })}`, { schema: z.array(reviewSchema) }),
    reviewTherapist: (
      id: string,
      review: { status: string; note?: string; licence_expires_on?: string },
    ) =>
      client.request(`/admin/therapists/${id}/verification`, {
        method: "PATCH",
        body: review,
        schema: reviewSchema,
      }),

    // structure
    departments: () => client.request("/admin/departments", { schema: z.array(departmentSchema) }),
    createDepartment: (input: { name: string; code: string }) =>
      client.request("/admin/departments", {
        method: "POST",
        body: input,
        schema: departmentSchema,
      }),
    updateDepartment: (id: string, patch: { name?: string; code?: string }) =>
      client.request(`/admin/departments/${id}`, {
        method: "PATCH",
        body: patch,
        schema: departmentSchema,
      }),
    deleteDepartment: (id: string) => client.request(`/admin/departments/${id}`, none),

    courses: (filter: { department_id?: string; term?: string; q?: string } = {}) =>
      client.request(`/admin/courses${qs(filter)}`, { schema: z.array(courseSchema) }),
    course: (id: string) => client.request(`/admin/courses/${id}`, { schema: courseDetailSchema }),
    createCourse: (input: {
      department_id: string;
      code: string;
      title: string;
      term: string;
      credits: number;
    }) => client.request("/admin/courses", { method: "POST", body: input, schema: courseSchema }),
    updateCourse: (id: string, patch: { title?: string; credits?: number }) =>
      client.request(`/admin/courses/${id}`, {
        method: "PATCH",
        body: patch,
        schema: courseSchema,
      }),
    deleteCourse: (id: string) => client.request(`/admin/courses/${id}`, none),
    assignTeacher: (course: string, teacher: string) =>
      client.request(`/admin/courses/${course}/teachers/${teacher}`, { method: "PUT" }),
    unassignTeacher: (course: string, teacher: string) =>
      client.request(`/admin/courses/${course}/teachers/${teacher}`, none),
    enrol: (course: string, student: string) =>
      client.request(`/admin/courses/${course}/students/${student}`, { method: "PUT" }),
    drop: (course: string, student: string) =>
      client.request(`/admin/courses/${course}/students/${student}`, none),

    // resources
    resources: (filter: {
      resource_type?: string;
      published?: boolean;
      source?: string;
      q?: string;
    }) => client.request(`/admin/resources${qs(filter)}`, { schema: z.array(adminResourceSchema) }),
    resource: (id: string) =>
      client.request(`/admin/resources/${id}`, { schema: adminResourceSchema }),
    createResource: (input: ResourceInput) =>
      client.request("/admin/resources", {
        method: "POST",
        body: input,
        schema: adminResourceSchema,
      }),
    updateResource: (id: string, input: ResourceInput) =>
      client.request(`/admin/resources/${id}`, {
        method: "PUT",
        body: input,
        schema: adminResourceSchema,
      }),
    setPublished: (id: string, published: boolean) =>
      client.request(`/admin/resources/${id}/publication`, {
        method: "PATCH",
        body: { published },
        schema: adminResourceSchema,
      }),
    deleteResource: (id: string) => client.request(`/admin/resources/${id}`, none),

    // aggregates
    analytics: (weeks: WindowWeeks) =>
      client.request(`/admin/analytics${qs({ weeks })}`, { schema: platformAnalyticsSchema }),
    oversight: (weeks: WindowWeeks) =>
      client.request(`/admin/appointments/oversight${qs({ weeks })}`, {
        schema: oversightSchema,
      }),

    // audit
    audit: (filter: AuditFilter & { before_seq?: number; limit?: number }) =>
      client.request(`/admin/audit${qs({ ...filter })}`, { schema: z.array(auditEventSchema) }),
    auditActions: () => client.request("/admin/audit/actions", { schema: z.array(z.string()) }),
    verifyAuditChain: () =>
      client.request("/admin/audit/verify", { method: "POST", schema: chainStatusSchema }),
    auditCsv: (filter: AuditFilter) =>
      client.request<string>(`/admin/audit/export${qs({ ...filter })}`, {
        responseType: "text",
      }),

    // settings
    institution: () => client.request("/admin/config", { schema: institutionSchema }),
    updateInstitution: (patch: { name?: string; email_domains?: string[] }) =>
      client.request("/admin/config", { method: "PATCH", body: patch, schema: institutionSchema }),
    notificationSettings: () =>
      client.request("/admin/settings/notifications", { schema: notificationSettingsSchema }),
    updateNotificationSettings: (patch: Record<string, unknown>) =>
      client.request("/admin/settings/notifications", {
        method: "PATCH",
        body: patch,
        schema: notificationSettingsSchema,
      }),
    safetySettings: () =>
      client.request("/admin/settings/safety", { schema: safetySettingsSchema }),
    updateSafetySettings: (patch: Partial<SafetySettings["values"]>) =>
      client.request("/admin/settings/safety", {
        method: "PATCH",
        body: patch,
        schema: safetySettingsSchema,
      }),
    crisisContacts: () =>
      client.request("/admin/settings/crisis-contacts", { schema: z.array(crisisContactSchema) }),
    createContact: (input: ContactInput) =>
      client.request("/admin/settings/crisis-contacts", {
        method: "POST",
        body: input,
        schema: crisisContactSchema,
      }),
    updateContact: (id: string, patch: Partial<ContactInput>) =>
      client.request(`/admin/settings/crisis-contacts/${id}`, {
        method: "PATCH",
        body: patch,
        schema: crisisContactSchema,
      }),
    deleteContact: (id: string) => client.request(`/admin/settings/crisis-contacts/${id}`, none),
  };
}

export type AdminApi = ReturnType<typeof createAdminApi>;
