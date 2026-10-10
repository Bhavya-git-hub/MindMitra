"use client";

import * as React from "react";

import { createCompanionApi, type CompanionApi } from "@/lib/api/companion-api";
import { useAuth } from "@/lib/auth/auth-context";

/** The companion API bound to the signed-in session's client. */
export function useCompanionApi(): CompanionApi {
  const { manager } = useAuth();
  return React.useMemo(() => createCompanionApi(manager.api), [manager]);
}
