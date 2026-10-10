"use client";

import * as React from "react";

import { createAdminApi, type AdminApi } from "@/lib/api/admin-api";
import { useAuth } from "@/lib/auth/auth-context";

/** The administrator API bound to the signed-in session's client. */
export function useAdminApi(): AdminApi {
  const { manager } = useAuth();
  return React.useMemo(() => createAdminApi(manager.api), [manager]);
}
