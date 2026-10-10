"use client";

import { Lock } from "lucide-react";
import * as React from "react";

import { SegmentedTabs } from "@/components/therapist/shared";
import { Badge } from "@/components/ui/badge";
import { WINDOW_WEEKS, type Share, type WindowWeeks } from "@/lib/api/teacher-schemas";

type Variant = "success" | "info" | "warning" | "outline";

export function WindowTabs({
  value,
  onChange,
}: {
  value: WindowWeeks;
  onChange: (weeks: WindowWeeks) => void;
}) {
  return (
    <SegmentedTabs
      label="Time window"
      value={String(value) as `${WindowWeeks}`}
      onChange={(v) => onChange(Number(v) as WindowWeeks)}
      options={WINDOW_WEEKS.map((w) => ({
        value: String(w) as `${WindowWeeks}`,
        label: `${w} weeks`,
      }))}
    />
  );
}

/** A share in words: a rounded percentage, or a plain phrase when a number would be unsafe. */
export function ShareText({ share }: { share: Share }) {
  if (share.state === "hidden") {
    return <span className="text-muted-foreground">Not enough students</span>;
  }
  return <span>{share.text}</span>;
}

export const REFERRAL_STATUS_VARIANT: Record<string, Variant> = {
  received: "info",
  in_progress: "warning",
  closed: "success",
};

export const REQUEST_STATUS_VARIANT: Record<string, Variant> = {
  open: "info",
  acknowledged: "warning",
  closed: "success",
  withdrawn: "outline",
};

export const URGENCY_VARIANT: Record<string, Variant> = {
  routine: "outline",
  soon: "info",
  urgent: "warning",
};

export function StatusBadge({
  status,
  label,
  variants,
}: {
  status: string;
  label: string;
  variants: Record<string, Variant>;
}) {
  return <Badge variant={variants[status] ?? "outline"}>{label}</Badge>;
}

/** The one-line reminder shown wherever a teacher is looking at group figures. */
export function PrivacyNote({ children }: { children?: React.ReactNode }) {
  return (
    <p className="flex items-start gap-2 text-sm text-muted-foreground">
      <Lock className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
      <span>
        {children ??
          "Figures describe groups of students who chose to share anonymous summaries. You can never see an individual student's check-ins, journal, conversations or notes."}
      </span>
    </p>
  );
}
