import * as React from "react";

import { Header } from "@/components/layout/header";
import { Sidebar } from "@/components/layout/sidebar";
import { SkipLink } from "@/components/layout/skip-link";
import type { Role } from "@/lib/auth/roles";
import { RealtimeProvider } from "@/lib/realtime/realtime-provider";

/**
 * The signed-in frame: sidebar on wide screens, a menu sheet on narrow ones, a sticky header,
 * and a single <main> landmark that the skip link targets. Everything inside shares one
 * real-time connection for live updates.
 */
export function AppShell({ role, children }: { role: Role; children: React.ReactNode }) {
  return (
    <RealtimeProvider>
      <div className="min-h-dvh md:grid md:grid-cols-[16rem_minmax(0,1fr)]">
        <SkipLink />
        <Sidebar role={role} />
        <div className="flex min-w-0 flex-col">
          <Header role={role} />
          <main
            id="main-content"
            tabIndex={-1}
            className="mx-auto w-full max-w-6xl flex-1 space-y-8 px-4 py-6 outline-none sm:px-6 sm:py-8"
          >
            {children}
          </main>
        </div>
      </div>
    </RealtimeProvider>
  );
}
