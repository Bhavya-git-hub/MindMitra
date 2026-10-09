import { RotateCw, TriangleAlert } from "lucide-react";
import * as React from "react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

/**
 * A gentle full-section error. Messages are plain language and never show stack traces; a
 * support reference (the API's request id, or the Next.js error digest) helps staff find it.
 */
export function ErrorState({
  title = "Something didn't load",
  description = "This is on our side, not yours. Please try again in a moment.",
  reference,
  onRetry,
  actions,
  className,
}: {
  title?: string;
  description?: string;
  reference?: string | null;
  onRetry?: () => void;
  actions?: React.ReactNode;
  className?: string;
}) {
  return (
    <div
      role="alert"
      className={cn(
        "mx-auto flex max-w-lg flex-col items-center gap-3 rounded-xl border bg-card px-6 py-10 text-center shadow-soft",
        className,
      )}
    >
      <span className="grid size-12 place-items-center rounded-full bg-warning-soft text-warning">
        <TriangleAlert className="size-6" aria-hidden="true" />
      </span>
      <h2 className="text-lg font-semibold">{title}</h2>
      <p className="text-sm text-muted-foreground">{description}</p>
      {reference && (
        <p className="text-xs text-muted-foreground">
          Reference: <code className="font-mono">{reference}</code>
        </p>
      )}
      <div className="flex flex-wrap justify-center gap-2 pt-2">
        {onRetry && (
          <Button onClick={onRetry}>
            <RotateCw aria-hidden="true" />
            Try again
          </Button>
        )}
        {actions}
      </div>
    </div>
  );
}
