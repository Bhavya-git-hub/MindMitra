"use client";

import { Loader2 } from "lucide-react";
import * as React from "react";

import { Button } from "@/components/ui/button";
import { describeError } from "@/lib/api/errors";
import { cn } from "@/lib/utils";

/** Runs one save at a time and keeps a friendly message from the API's own problem details. */
export function useSubmit() {
  const [pending, setPending] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  async function run(
    action: () => Promise<void>,
    fallback = "We couldn't save that. Please try again.",
  ) {
    setPending(true);
    setError(null);
    try {
      await action();
    } catch (e) {
      setError(describeError(e, fallback));
    } finally {
      setPending(false);
    }
  }
  return { pending, error, run, clearError: () => setError(null) };
}

export function SaveButton({
  pending,
  children,
  ...props
}: { pending: boolean } & React.ComponentProps<typeof Button>) {
  return (
    <Button type="submit" disabled={pending} {...props}>
      {pending && <Loader2 className="animate-spin" aria-hidden="true" />}
      {children}
    </Button>
  );
}

/** A native <select> styled like the other inputs: reliable on phones and with assistive tech. */
export function NativeSelect({ className, ...props }: React.ComponentProps<"select">) {
  return (
    <select
      className={cn(
        "flex h-10 w-full min-w-0 rounded-lg border border-input bg-card px-3 py-2 text-base shadow-xs outline-none md:text-sm",
        "focus-visible:border-ring focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background",
        "disabled:cursor-not-allowed disabled:opacity-50",
        className,
      )}
      {...props}
    />
  );
}
