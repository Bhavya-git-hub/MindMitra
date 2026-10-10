"use client";

import * as React from "react";

import { createStudentApi, type StudentApi } from "@/lib/api/student-api";
import { useAuth } from "@/lib/auth/auth-context";

/** The student API bound to the signed-in session's client. */
export function useStudentApi(): StudentApi {
  const { manager } = useAuth();
  return React.useMemo(() => createStudentApi(manager.api), [manager]);
}
