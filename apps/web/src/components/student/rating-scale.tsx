"use client";

import * as React from "react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

/**
 * A 1-to-5 choice built from native radio buttons, so keyboard and screen-reader behaviour is
 * the browser's own. Each option shows its number and a word, so meaning never depends on colour.
 */
export function RatingScale({
  legend,
  hint,
  labels,
  value,
  onChange,
  optional = false,
  error,
}: {
  legend: string;
  hint?: string;
  labels: Record<number, string>;
  value: number | undefined;
  onChange: (value: number | undefined) => void;
  /** Optional scales can be cleared again. */
  optional?: boolean;
  error?: string;
}) {
  const name = React.useId();
  const hintId = `${name}-hint`;
  const errorId = `${name}-error`;
  return (
    <fieldset
      className="space-y-2"
      aria-describedby={cn(hint && hintId, error && errorId) || undefined}
    >
      <legend className="text-sm font-medium">{legend}</legend>
      {hint && (
        <p id={hintId} className="text-sm text-muted-foreground">
          {hint}
        </p>
      )}
      <div className="grid grid-cols-5 gap-2">
        {[1, 2, 3, 4, 5].map((n) => (
          <label key={n} className="relative cursor-pointer">
            <input
              type="radio"
              name={name}
              value={n}
              checked={value === n}
              onChange={() => onChange(n)}
              className="peer sr-only"
            />
            <span
              className={cn(
                "flex min-h-16 flex-col items-center justify-center gap-0.5 rounded-xl border bg-card px-1 py-2 text-center text-xs transition-colors sm:text-sm",
                "peer-checked:border-primary peer-checked:bg-primary peer-checked:text-primary-foreground",
                "peer-focus-visible:ring-[3px] peer-focus-visible:ring-ring/50",
                "hover:bg-accent peer-checked:hover:bg-primary",
              )}
            >
              <span className="text-lg font-semibold" aria-hidden="true">
                {n}
              </span>
              <span>{labels[n]}</span>
            </span>
          </label>
        ))}
      </div>
      {optional && value !== undefined && (
        <Button type="button" variant="ghost" size="sm" onClick={() => onChange(undefined)}>
          Clear
        </Button>
      )}
      {error && (
        <p id={errorId} role="alert" className="text-sm text-destructive">
          {error}
        </p>
      )}
    </fieldset>
  );
}
