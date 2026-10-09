"use client";

import { useRouter } from "next/navigation";
import * as React from "react";

import { useAuth } from "@/lib/auth/auth-context";
import { notify } from "@/lib/toast";

/** Signs out, confirms with a toast and returns to /login. Shared by the header menu and the account page. */
export function useSignOut() {
  const { logout } = useAuth();
  const router = useRouter();
  const [signingOut, setSigningOut] = React.useState(false);

  const signOut = React.useCallback(async () => {
    setSigningOut(true);
    await logout();
    notify.success("You're signed out", "Take care of yourself.");
    router.replace("/login");
  }, [logout, router]);

  return { signOut, signingOut };
}
