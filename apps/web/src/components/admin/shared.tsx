"use client";

import { ChevronLeft, ChevronRight, Search } from "lucide-react";
import * as React from "react";

import { InlineAlert } from "@/components/states/inline-alert";
import { SaveButton } from "@/components/student/form-bits";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { titleCase } from "@/lib/format";

type Variant = "success" | "info" | "warning" | "outline";

export const USER_STATUS_VARIANT: Record<string, Variant> = {
  active: "success",
  invited: "info",
  suspended: "warning",
  deactivated: "outline",
};

export const ROLE_LABELS: Record<string, string> = {
  student: "Student",
  teacher: "Teacher",
  therapist: "Therapist",
  administrator: "Administrator",
};

export function UserStatusBadge({ status }: { status: string }) {
  return <Badge variant={USER_STATUS_VARIANT[status] ?? "outline"}>{titleCase(status)}</Badge>;
}

/** Waits for the typing to stop before the value changes, so a search is not a request per key. */
export function useDebounced<T>(value: T, ms = 300): T {
  const [debounced, setDebounced] = React.useState(value);
  React.useEffect(() => {
    const id = setTimeout(() => setDebounced(value), ms);
    return () => clearTimeout(id);
  }, [value, ms]);
  return debounced;
}

export function SearchBox({
  label,
  value,
  onChange,
  placeholder,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
}) {
  const id = React.useId();
  return (
    <div className="relative w-full max-w-sm">
      <Label htmlFor={id} className="sr-only">
        {label}
      </Label>
      <Search
        className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground"
        aria-hidden="true"
      />
      <Input
        id={id}
        type="search"
        value={value}
        placeholder={placeholder ?? label}
        maxLength={80}
        className="pl-9"
        onChange={(e) => onChange(e.target.value)}
      />
    </div>
  );
}

export function Pager({
  offset,
  limit,
  total,
  onChange,
}: {
  offset: number;
  limit: number;
  total: number;
  onChange: (offset: number) => void;
}) {
  if (total === 0) return null;
  const from = offset + 1;
  const to = Math.min(offset + limit, total);
  return (
    <nav
      aria-label="Pages"
      className="flex flex-wrap items-center justify-between gap-3 pt-4 text-sm"
    >
      <p aria-live="polite" className="text-muted-foreground">
        Showing {from} to {to} of {total}
      </p>
      <div className="flex gap-2">
        <Button
          type="button"
          variant="outline"
          size="sm"
          disabled={offset === 0}
          onClick={() => onChange(Math.max(0, offset - limit))}
        >
          <ChevronLeft aria-hidden="true" />
          Previous
        </Button>
        <Button
          type="button"
          variant="outline"
          size="sm"
          disabled={offset + limit >= total}
          onClick={() => onChange(offset + limit)}
        >
          Next
          <ChevronRight aria-hidden="true" />
        </Button>
      </div>
    </nav>
  );
}

/**
 * A table that scrolls sideways on a phone instead of squeezing its columns. It is `relative` so
 * the visually hidden text inside its cells (which is absolutely positioned) is clipped with the
 * table instead of widening the whole page.
 */
export function Table({
  caption,
  head,
  children,
  minWidth = "40rem",
}: {
  caption: string;
  head: string[];
  children: React.ReactNode;
  minWidth?: string;
}) {
  return (
    <div className="relative overflow-x-auto">
      <table className="w-full text-left text-sm" style={{ minWidth }}>
        <caption className="sr-only">{caption}</caption>
        <thead>
          <tr className="border-b text-muted-foreground">
            {head.map((h) => (
              <th key={h} scope="col" className="py-2 pr-4 font-medium">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y">{children}</tbody>
      </table>
    </div>
  );
}

/** A dialog with a title and a form inside. The parent owns `open`. */
export function FormDialog({
  open,
  onClose,
  title,
  description,
  children,
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  description?: string;
  children: React.ReactNode;
}) {
  return (
    <Dialog open={open} onOpenChange={(next) => !next && onClose()}>
      <DialogContent className="max-h-[90dvh] overflow-y-auto sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          {description && <DialogDescription>{description}</DialogDescription>}
        </DialogHeader>
        {children}
      </DialogContent>
    </Dialog>
  );
}

/** A labelled input row used by the dialogs: label, control, and an inline error. */
export function Field({
  label,
  hint,
  error,
  children,
}: {
  label: string;
  hint?: string;
  error?: string;
  children: (props: {
    id: string;
    "aria-invalid"?: true;
    "aria-describedby"?: string;
  }) => React.ReactNode;
}) {
  const id = React.useId();
  const describedBy = [hint ? `${id}-hint` : null, error ? `${id}-error` : null]
    .filter(Boolean)
    .join(" ");
  return (
    <div className="space-y-2">
      <Label htmlFor={id}>{label}</Label>
      {children({
        id,
        ...(error ? { "aria-invalid": true as const } : {}),
        ...(describedBy ? { "aria-describedby": describedBy } : {}),
      })}
      {hint && (
        <p id={`${id}-hint`} className="text-sm text-muted-foreground">
          {hint}
        </p>
      )}
      {error && (
        <p id={`${id}-error`} role="alert" className="text-sm text-destructive">
          {error}
        </p>
      )}
    </div>
  );
}

export function FormActions({
  pending,
  error,
  onCancel,
  submit = "Save",
}: {
  pending: boolean;
  error: string | null;
  onCancel: () => void;
  submit?: string;
}) {
  return (
    <div className="space-y-3 pt-2">
      {error && <InlineAlert tone="destructive">{error}</InlineAlert>}
      <div className="flex flex-wrap justify-end gap-2">
        <Button type="button" variant="ghost" onClick={onCancel}>
          Cancel
        </Button>
        <SaveButton pending={pending}>{submit}</SaveButton>
      </div>
    </div>
  );
}

/** Splits a comma-separated field into trimmed, non-empty items. */
export const splitList = (text: string): string[] =>
  text
    .split(",")
    .map((t) => t.trim())
    .filter(Boolean);
