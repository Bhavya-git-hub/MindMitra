"use client";

import * as React from "react";

import { createTeacherApi, type TeacherApi } from "@/lib/api/teacher-api";
import { useAuth } from "@/lib/auth/auth-context";

/** The teacher-portal API bound to the signed-in session's client. */
export function useTeacherApi(): TeacherApi {
  const { manager } = useAuth();
  return React.useMemo(() => createTeacherApi(manager.api), [manager]);
}
