"use client";

import Link from "next/link";
import * as React from "react";

import { ErrorState } from "@/components/states/error-state";
import { Button } from "@/components/ui/button";

/** Shared body of every route-level `error.tsx`. The raw error is never shown to people. */
export function RouteError({
  error,
  reset,
  homeHref = "/",
}: {
  error: Error & { digest?: string };
  reset: () => void;
  homeHref?: string;
}) {
  React.useEffect(() => {
    // Replace with the observability hook when it exists; never log user content here.
    console.error("Route error", error.digest ?? "no-digest");
  }, [error]);

  return (
    <ErrorState
      reference={error.digest}
      onRetry={reset}
      actions={
        <Button asChild variant="outline">
          <Link href={homeHref}>Back to overview</Link>
        </Button>
      }
    />
  );
}
