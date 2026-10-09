/**
 * Roles and portals. Role names are the API's `user_role` values; the administrator portal
 * lives at /admin. Frontend routing is UX only: the API is the single enforcement point.
 */

export const ROLES = ["student", "therapist", "teacher", "administrator"] as const;
export type Role = (typeof ROLES)[number];

export const PORTAL_PATHS: Record<Role, string> = {
  student: "/student",
  therapist: "/therapist",
  teacher: "/teacher",
  administrator: "/admin",
};

export const ROLE_LABELS: Record<Role, string> = {
  student: "Student",
  therapist: "Therapist",
  teacher: "Teacher",
  administrator: "Administrator",
};

export function isRole(value: unknown): value is Role {
  return typeof value === "string" && (ROLES as readonly string[]).includes(value);
}

export function portalFor(role: Role): string {
  return PORTAL_PATHS[role];
}

/** The portal a pathname belongs to, or null for public and unknown paths. */
export function roleForPath(pathname: string): Role | null {
  for (const role of ROLES) {
    const base = PORTAL_PATHS[role];
    if (pathname === base || pathname.startsWith(`${base}/`)) return role;
  }
  return null;
}
