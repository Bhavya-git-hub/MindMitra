"use client";

import { usePathname, useRouter } from "next/navigation";
import * as React from "react";

import { LoadingState } from "@/components/states/loading-state";
import { useAuth } from "@/lib/auth/auth-context";
import { portalFor, type Role } from "@/lib/auth/roles";

/**
 * Client-side guard for a portal. It waits for the session to be restored, sends signed-out
 * visitors to /login (remembering where they were going) and signed-in people with a different
 * role to their own portal. This is a UX layer: every API call is authorized by the server.
 */
export function AuthGate({ role, children }: { role: Role; children: React.ReactNode }) {
  const { status, user, signedOutReason } = useAuth();
  const router = useRouter();
  const pathname = usePathname();

  const redirectTo =
    status === "unauthenticated"
      ? // After an explicit sign-out the person is not "heading somewhere", so no next=.
        signedOutReason === "user"
        ? "/login"
        : `/login?next=${encodeURIComponent(pathname)}`
      : status === "authenticated" && user && user.role !== role
        ? portalFor(user.role)
        : null;

  React.useEffect(() => {
    if (redirectTo) router.replace(redirectTo);
  }, [redirectTo, router]);

  if (status === "authenticated" && user?.role === role) return <>{children}</>;

  return (
    <div className="grid min-h-dvh place-items-center">
      <LoadingState
        page
        label={redirectTo ? "Taking you to the right place…" : "Checking your session…"}
      />
    </div>
  );
}
