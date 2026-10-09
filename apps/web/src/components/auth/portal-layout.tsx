"use client";

import * as React from "react";

import { AuthGate } from "@/components/auth/auth-gate";
import { AppShell } from "@/components/layout/app-shell";
import type { Role } from "@/lib/auth/roles";

/** Layout used by each portal route group: guard first, then the app shell. */
export function PortalLayout({ role, children }: { role: Role; children: React.ReactNode }) {
  return (
    <AuthGate role={role}>
      <AppShell role={role}>{children}</AppShell>
    </AuthGate>
  );
}
