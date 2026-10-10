"use client";

import { Check } from "lucide-react";
import * as React from "react";

import { cn } from "@/lib/utils";

/** Pick any number of short labels. Selected chips show a tick as well as a colour. */
export function ChipGroup({
  legend,
  hint,
  options,
  value,
  onChange,
  max = 8,
}: {
  legend: string;
  hint?: string;
  options: readonly string[];
  value: string[];
  onChange: (value: string[]) => void;
  max?: number;
}) {
  const id = React.useId();
  function toggle(option: string) {
    if (value.includes(option)) onChange(value.filter((v) => v !== option));
    else if (value.length < max) onChange([...value, option]);
  }
  return (
    <fieldset className="space-y-2" aria-describedby={hint ? `${id}-hint` : undefined}>
      <legend className="text-sm font-medium">{legend}</legend>
      {hint && (
        <p id={`${id}-hint`} className="text-sm text-muted-foreground">
          {hint}
        </p>
      )}
      <div className="flex flex-wrap gap-2">
        {options.map((option) => {
          const selected = value.includes(option);
          return (
            <button
              key={option}
              type="button"
              aria-pressed={selected}
              onClick={() => toggle(option)}
              className={cn(
                "inline-flex min-h-10 items-center gap-1.5 rounded-full border px-4 text-sm capitalize transition-colors",
                "focus-visible:ring-[3px] focus-visible:ring-ring/50 focus-visible:outline-none",
                selected
                  ? "border-primary bg-primary text-primary-foreground"
                  : "bg-card hover:bg-accent",
              )}
            >
              {selected && <Check className="size-4" aria-hidden="true" />}
              {option}
            </button>
          );
        })}
      </div>
    </fieldset>
  );
}
