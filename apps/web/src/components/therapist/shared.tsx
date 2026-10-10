"use client";

import { ShieldAlert } from "lucide-react";
import Link from "next/link";
import * as React from "react";

import { InlineAlert } from "@/components/states/inline-alert";
import { DataView } from "@/components/student/data-view";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useQuery, type QueryResult } from "@/lib/hooks/use-query";
import { useTherapistApi } from "@/lib/hooks/use-therapist-api";
import type { TherapistProfile } from "@/lib/api/therapist-schemas";

type Variant = "success" | "info" | "warning" | "outline";

const STATUS_VARIANT: Record<string, Variant> = {
  verified: "success",
  pending: "info",
  rejected: "warning",
  expired: "warning",
};

export function VerificationBadge({ status, label }: { status: string; label: string }) {
  return <Badge variant={STATUS_VARIANT[status] ?? "outline"}>{label}</Badge>;
}

/** The therapist's own profile, shared by every page that needs to know if they are verified. */
export function useTherapistProfile(): QueryResult<TherapistProfile> {
  const api = useTherapistApi();
  return useQuery("therapist-profile", () => api.profile());
}

export function VerificationNotice({ label }: { label: string }) {
  return (
    <InlineAlert tone="info" title={label}>
      Student information opens once an administrator has verified your professional registration.{" "}
      <Link href="/therapist/profile" className="font-medium underline underline-offset-4">
        Check your verification
      </Link>
    </InlineAlert>
  );
}

/**
 * Pages that work with students render only for a verified therapist. This is a courtesy: the
 * API refuses the same requests (403) whatever this component shows.
 */
export function RequireVerified({ children }: { children: React.ReactNode }) {
  const profile = useTherapistProfile();
  return (
    <DataView query={profile}>
      {(p) =>
        p.can_see_students ? (
          <>{children}</>
        ) : (
          <div className="space-y-4">
            <VerificationNotice label={p.verification_label} />
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <ShieldAlert className="size-4" aria-hidden="true" />
              Students, notes, alerts and messages stay closed until then.
            </div>
          </div>
        )
      }
    </DataView>
  );
}

export function ConfirmDialog({
  open,
  onOpenChange,
  title,
  description,
  confirmLabel,
  cancelLabel = "Keep it",
  pending,
  error,
  onConfirm,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description: string;
  confirmLabel: string;
  cancelLabel?: string;
  pending: boolean;
  error?: string | null;
  onConfirm: () => void;
}) {
  return (
    <AlertDialog open={open} onOpenChange={onOpenChange}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>{title}</AlertDialogTitle>
          <AlertDialogDescription>{description}</AlertDialogDescription>
        </AlertDialogHeader>
        {error && <InlineAlert tone="destructive">{error}</InlineAlert>}
        <AlertDialogFooter>
          <AlertDialogCancel>{cancelLabel}</AlertDialogCancel>
          <AlertDialogAction
            disabled={pending}
            onClick={(e) => {
              e.preventDefault();
              onConfirm();
            }}
          >
            {confirmLabel}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}

export function SegmentedTabs<T extends string>({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: T;
  options: { value: T; label: string }[];
  onChange: (value: T) => void;
}) {
  return (
    <div role="group" aria-label={label} className="flex flex-wrap gap-2">
      {options.map((o) => (
        <Button
          key={o.value}
          type="button"
          size="sm"
          variant={value === o.value ? "default" : "outline"}
          aria-pressed={value === o.value}
          onClick={() => onChange(o.value)}
        >
          {o.label}
        </Button>
      ))}
    </div>
  );
}

export const SEVERITY_LABELS: Record<string, string> = {
  imminent: "Needs a person now",
  high: "High priority",
  moderate: "Moderate",
  low: "Low",
};

export const SEVERITY_VARIANT: Record<string, Variant> = {
  imminent: "warning",
  high: "warning",
  moderate: "info",
  low: "outline",
};
