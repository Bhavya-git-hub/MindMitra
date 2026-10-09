"use client";

import Link from "next/link";
import * as React from "react";

import { AuthCard } from "@/components/auth/auth-card";
import { InlineAlert } from "@/components/states/inline-alert";
import { LoadingState } from "@/components/states/loading-state";
import { Button } from "@/components/ui/button";
import { describeError, isApiError } from "@/lib/api/errors";
import { useAuth } from "@/lib/auth/auth-context";

type State = { phase: "verifying" } | { phase: "done" } | { phase: "failed"; message: string };

/** Confirms the one-time token from the verification email exactly once. */
export function VerifyEmailView({ token }: { token?: string }) {
  const { manager } = useAuth();
  const [state, setState] = React.useState<State>({ phase: "verifying" });
  // The token is single use, so React StrictMode's second effect run must not call twice.
  const started = React.useRef(false);

  React.useEffect(() => {
    if (!token || started.current) return;
    started.current = true;
    manager.auth
      .verifyEmail(token)
      .then(() => setState({ phase: "done" }))
      .catch((error: unknown) =>
        setState({
          phase: "failed",
          message:
            isApiError(error) && (error.status === 401 || error.status === 400)
              ? "This link has expired or was already used."
              : describeError(error),
        }),
      );
  }, [token, manager]);

  if (!token) {
    return (
      <AuthCard title="This link isn't complete">
        <InlineAlert tone="warning">Open the link from your verification email again.</InlineAlert>
      </AuthCard>
    );
  }

  if (state.phase === "verifying") {
    return (
      <AuthCard title="Verifying your email">
        <LoadingState label="Verifying…" />
      </AuthCard>
    );
  }

  if (state.phase === "done") {
    return (
      <AuthCard title="Email verified">
        <InlineAlert tone="success">Thank you. Your account is ready.</InlineAlert>
        <Button asChild className="w-full">
          <Link href="/login">Sign in</Link>
        </Button>
      </AuthCard>
    );
  }

  return (
    <AuthCard title="We couldn't verify your email">
      <InlineAlert tone="destructive">{state.message}</InlineAlert>
      <Button asChild variant="outline" className="w-full">
        <Link href="/register">Start again</Link>
      </Button>
    </AuthCard>
  );
}
