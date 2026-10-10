"use client";

import { CalendarDays } from "lucide-react";
import * as React from "react";

import { InlineAlert } from "@/components/states/inline-alert";
import { NativeSelect, SaveButton, useSubmit } from "@/components/student/form-bits";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { CANCEL_REASONS, type CancelReason } from "@/lib/api/student-schemas";
import { formatDay, formatTime, modeLabel } from "@/lib/format";

/** A time someone could move an appointment to. */
export interface OpenTime {
  id: string;
  starts_at: string;
  ends_at: string;
  mode: string;
}

/** An optional reason, from a fixed list (free text could carry more than the person meant). */
export function CancelReasonField({
  value,
  onChange,
  reasons = CANCEL_REASONS,
}: {
  value: CancelReason | "";
  onChange: (value: CancelReason | "") => void;
  reasons?: readonly { value: CancelReason; label: string }[];
}) {
  const id = React.useId();
  return (
    <div className="space-y-2">
      <Label htmlFor={id}>Reason (optional)</Label>
      <NativeSelect
        id={id}
        value={value}
        onChange={(e) => onChange(e.target.value as CancelReason | "")}
      >
        <option value="">Prefer not to say</option>
        {reasons.map((r) => (
          <option key={r.value} value={r.value}>
            {r.label}
          </option>
        ))}
      </NativeSelect>
    </div>
  );
}

function groupByDay(times: OpenTime[]): [string, OpenTime[]][] {
  const groups = new Map<string, OpenTime[]>();
  for (const t of times) {
    const day = formatDay(t.starts_at);
    groups.set(day, [...(groups.get(day) ?? []), t]);
  }
  return [...groups.entries()];
}

/**
 * Pick another open time for an appointment. The times are loaded when the dialog opens, so they
 * are current; the server still refuses a time that has just been taken.
 */
export function RescheduleDialog({
  open,
  onOpenChange,
  description,
  note,
  loadTimes,
  onMove,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  description: string;
  /** What happens after moving, in a sentence. */
  note: string;
  loadTimes: () => Promise<OpenTime[]>;
  onMove: (timeId: string) => Promise<void>;
}) {
  const [times, setTimes] = React.useState<OpenTime[] | null>(null);
  const [loadError, setLoadError] = React.useState(false);
  const [chosen, setChosen] = React.useState<string>("");
  const { pending, error, run, clearError } = useSubmit();
  const load = React.useRef(loadTimes);
  React.useEffect(() => {
    load.current = loadTimes;
  });

  // Each opening starts clean (adjusting state while rendering, as React recommends over an
  // effect), then loads the times fresh.
  const [wasOpen, setWasOpen] = React.useState(open);
  if (open !== wasOpen) {
    setWasOpen(open);
    if (open) {
      setTimes(null);
      setLoadError(false);
      setChosen("");
    }
  }

  React.useEffect(() => {
    if (!open) return;
    let live = true;
    load.current().then(
      (list) => live && setTimes(list),
      () => live && setLoadError(true),
    );
    return () => {
      live = false;
    };
  }, [open]);

  function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!chosen) return;
    void run(
      () => onMove(chosen),
      "We couldn't move it to that time. It may have just been taken, so please pick another.",
    );
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next) clearError();
        onOpenChange(next);
      }}
    >
      <DialogContent className="max-h-[90dvh] overflow-y-auto">
        <form onSubmit={submit} className="space-y-4" noValidate>
          <DialogHeader>
            <DialogTitle>Move this appointment</DialogTitle>
            <DialogDescription>
              {description} {note}
            </DialogDescription>
          </DialogHeader>
          {loadError ? (
            <InlineAlert tone="destructive">
              We couldn&apos;t load the open times. Please close this and try again.
            </InlineAlert>
          ) : times === null ? (
            <p className="text-sm text-muted-foreground">Loading open times…</p>
          ) : times.length === 0 ? (
            <div className="flex items-start gap-2 text-sm text-muted-foreground">
              <CalendarDays className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
              <p>There are no other open times right now.</p>
            </div>
          ) : (
            <fieldset className="space-y-4">
              <legend className="mb-2 text-sm font-medium">Choose a new time</legend>
              {groupByDay(times).map(([day, list]) => (
                <div key={day} className="space-y-2">
                  <p className="text-sm font-medium text-muted-foreground">{day}</p>
                  <div className="flex flex-wrap gap-2">
                    {list.map((t) => (
                      <label
                        key={t.id}
                        className="flex cursor-pointer items-center gap-2 rounded-lg border px-3 py-2 text-sm has-[:checked]:border-primary has-[:checked]:bg-primary/10 has-[:focus-visible]:ring-2 has-[:focus-visible]:ring-ring"
                      >
                        <input
                          type="radio"
                          name="new-time"
                          value={t.id}
                          checked={chosen === t.id}
                          onChange={() => setChosen(t.id)}
                          className="size-4 accent-primary"
                        />
                        <span>
                          {formatTime(t.starts_at)}
                          <span className="sr-only">, {day}</span>
                          <span className="text-muted-foreground"> · {modeLabel(t.mode)}</span>
                        </span>
                      </label>
                    ))}
                  </div>
                </div>
              ))}
            </fieldset>
          )}
          {error && <InlineAlert tone="destructive">{error}</InlineAlert>}
          <DialogFooter>
            <Button type="button" variant="ghost" onClick={() => onOpenChange(false)}>
              Keep the current time
            </Button>
            <SaveButton pending={pending} disabled={pending || !chosen}>
              Move appointment
            </SaveButton>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
