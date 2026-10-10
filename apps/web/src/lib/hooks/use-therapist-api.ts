"use client";

import * as React from "react";

import { createTherapistApi, type TherapistApi } from "@/lib/api/therapist-api";
import { useAuth } from "@/lib/auth/auth-context";

/** The therapist API bound to the signed-in session's client. */
export function useTherapistApi(): TherapistApi {
  const { manager } = useAuth();
  return React.useMemo(() => createTherapistApi(manager.api), [manager]);
}
