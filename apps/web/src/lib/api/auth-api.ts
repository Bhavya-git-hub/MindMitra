/** Typed wrappers for the API's authentication endpoints (API_DESIGN.md section 2.1). */
import type { ApiClient } from "./client";
import { acceptedSchema, meSchema, tokenOutSchema } from "./schemas";

export interface LoginInput {
  email: string;
  password: string;
  /** Only needed when the same e-mail exists in more than one institution. */
  institution?: string;
}

export interface RegisterInput {
  email: string;
  password: string;
  full_name: string;
  department_code: string;
  student_number: string;
  enrollment_year: number;
  year_of_study: number;
  accept_terms: true;
}

export function createAuthApi(client: ApiClient) {
  return {
    login: (input: LoginInput) =>
      client.request("/auth/login", {
        method: "POST",
        body: input,
        schema: tokenOutSchema,
        auth: false,
      }),

    /** Cookie-authenticated: the refresh cookie rides along, the CSRF token is the proof. */
    refresh: (csrfToken: string) =>
      client.request("/auth/refresh", {
        method: "POST",
        schema: tokenOutSchema,
        auth: false,
        headers: { "X-CSRF-Token": csrfToken },
      }),

    logout: () => client.request("/auth/logout", { method: "POST" }),

    me: () => client.request("/me", { schema: meSchema }),

    register: (input: RegisterInput) =>
      client.request("/auth/register", {
        method: "POST",
        body: input,
        schema: acceptedSchema,
        auth: false,
      }),

    verifyEmail: (token: string) =>
      client.request("/auth/verify-email", {
        method: "POST",
        body: { token },
        schema: acceptedSchema,
        auth: false,
      }),

    forgotPassword: (email: string, institution?: string) =>
      client.request("/auth/password/forgot", {
        method: "POST",
        body: { email, institution },
        schema: acceptedSchema,
        auth: false,
      }),

    resetPassword: (token: string, newPassword: string) =>
      client.request("/auth/password/reset", {
        method: "POST",
        body: { token, new_password: newPassword },
        schema: acceptedSchema,
        auth: false,
      }),
  };
}

export type AuthApi = ReturnType<typeof createAuthApi>;
