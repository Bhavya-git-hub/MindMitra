"use client";

import { CalendarPlus, Trash2 } from "lucide-react";
import * as React from "react";

import { SectionCard } from "@/components/cards/section-card";
import { PageHeader } from "@/components/layout/page-header";
import { EmptyState } from "@/components/states/empty-state";
import { InlineAlert } from "@/components/states/inline-alert";
import { DataView } from "@/components/student/data-view";
import { NativeSelect, SaveButton, useSubmit } from "@/components/student/form-bits";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import type { AvailabilitySlot } from "@/lib/api/therapist-schemas";
import { formatDay, formatTime, modeLabel } from "@/lib/format";
import { useQuery } from "@/lib/hooks/use-query";
import { useTherapistApi } from "@/lib/hooks/use-therapist-api";
import { notify } from "@/lib/toast";

import { ConfirmDialog } from "./shared";

const DURATIONS = [30, 45, 50, 60, 90];

/** Local "2026-10-14" + "10:00" -> an ISO instant in the therapist's own zone. */
function toIso(date: string, time: string, addMinutes = 0): string {
  const start = new Date(`${date}T${time}`);
  return new Date(start.getTime() + addMinutes * 60_000).toISOString();
}

function AddSlotForm({ onAdded }: { onAdded: () => Promise<void> }) {
  const api = useTherapistApi();
  const [date, setDate] = React.useState("");
  const [time, setTime] = React.useState("10:00");
  const [minutes, setMinutes] = React.useState(50);
  const [mode, setMode] = React.useState<"video" | "in_person" | "phone">("video");
  const [repeat, setRepeat] = React.useState(0);
  const [dateError, setDateError] = React.useState<string>();
  const { pending, error, run } = useSubmit();

  function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!date || !time) {
      setDateError("Choose a date and a start time.");
      return;
    }
    setDateError(undefined);
    void run(async () => {
      const added = await api.addAvailability({
        starts_at: toIso(date, time),
        ends_at: toIso(date, time, minutes),
        mode,
        repeat_weeks: repeat,
      });
      notify.success(added.length === 1 ? "Time added" : `${added.length} times added`);
      await onAdded();
    }, "We couldn't add that time. Check it's in the future and doesn't overlap another.");
  }

  return (
    <form onSubmit={submit} className="grid gap-4 sm:grid-cols-2 lg:grid-cols-5" noValidate>
      <div className="space-y-2">
        <Label htmlFor="slot-date">Date</Label>
        <Input
          id="slot-date"
          type="date"
          value={date}
          onChange={(e) => setDate(e.target.value)}
          aria-invalid={dateError ? true : undefined}
          aria-describedby={dateError ? "slot-error" : undefined}
        />
      </div>
      <div className="space-y-2">
        <Label htmlFor="slot-time">Starts at</Label>
        <Input id="slot-time" type="time" value={time} onChange={(e) => setTime(e.target.value)} />
      </div>
      <div className="space-y-2">
        <Label htmlFor="slot-length">Length</Label>
        <NativeSelect
          id="slot-length"
          value={minutes}
          onChange={(e) => setMinutes(Number(e.target.value))}
        >
          {DURATIONS.map((d) => (
            <option key={d} value={d}>
              {d} minutes
            </option>
          ))}
        </NativeSelect>
      </div>
      <div className="space-y-2">
        <Label htmlFor="slot-mode">How</Label>
        <NativeSelect
          id="slot-mode"
          value={mode}
          onChange={(e) => setMode(e.target.value as typeof mode)}
        >
          <option value="video">Video call</option>
          <option value="in_person">In person</option>
          <option value="phone">Phone call</option>
        </NativeSelect>
      </div>
      <div className="space-y-2">
        <Label htmlFor="slot-repeat">Repeat weekly for</Label>
        <NativeSelect
          id="slot-repeat"
          value={repeat}
          onChange={(e) => setRepeat(Number(e.target.value))}
        >
          <option value={0}>Just this once</option>
          {[1, 2, 3, 4, 7, 11].map((n) => (
            <option key={n} value={n}>
              {n} more week{n === 1 ? "" : "s"}
            </option>
          ))}
        </NativeSelect>
      </div>
      <div className="space-y-3 sm:col-span-2 lg:col-span-5">
        {dateError && (
          <p id="slot-error" role="alert" className="text-sm text-destructive">
            {dateError}
          </p>
        )}
        {error && <InlineAlert tone="destructive">{error}</InlineAlert>}
        <SaveButton pending={pending}>
          <CalendarPlus aria-hidden="true" />
          Add availability
        </SaveButton>
      </div>
    </form>
  );
}

function groupByDay(slots: AvailabilitySlot[]): [string, AvailabilitySlot[]][] {
  const groups = new Map<string, AvailabilitySlot[]>();
  for (const slot of slots) {
    const day = formatDay(slot.starts_at);
    groups.set(day, [...(groups.get(day) ?? []), slot]);
  }
  return [...groups.entries()];
}

export function AvailabilityView() {
  const api = useTherapistApi();
  // A window that covers everything that can be added (about four months ahead).
  const [range] = React.useState(() => {
    const from = new Date();
    from.setHours(0, 0, 0, 0);
    const to = new Date(from.getTime() + 125 * 86_400_000);
    return { from: from.toISOString(), to: to.toISOString() };
  });
  const slots = useQuery(`availability-${range.from}`, () =>
    api.availability(range.from, range.to),
  );
  const [target, setTarget] = React.useState<AvailabilitySlot | null>(null);
  const { pending, error, run, clearError } = useSubmit();

  function remove() {
    if (!target) return;
    const id = target.id;
    void run(async () => {
      await api.removeAvailability(id);
      notify.success("Time removed");
      setTarget(null);
      await slots.reload();
    }, "We couldn't remove that time.");
  }

  return (
    <>
      <PageHeader
        title="Availability"
        description="The times students can ask to book. Times are shown in your own time zone."
      />
      <SectionCard title="Add times">
        <AddSlotForm onAdded={slots.reload} />
      </SectionCard>
      <DataView query={slots}>
        {(list) => (
          <SectionCard
            title="Your times"
            description="Upcoming openings, including ones already requested."
          >
            {list.length === 0 ? (
              <EmptyState
                icon={CalendarPlus}
                title="No times yet"
                description="Add some openings above. Students only see times for verified therapists."
              />
            ) : (
              <div className="space-y-6">
                {groupByDay(list).map(([day, daySlots]) => (
                  <section key={day} aria-label={day}>
                    <h3 className="mb-2 font-medium">{day}</h3>
                    <ul className="divide-y rounded-lg border">
                      {daySlots.map((s) => (
                        <li
                          key={s.id}
                          className="flex flex-wrap items-center justify-between gap-3 px-4 py-3"
                        >
                          <span>
                            {formatTime(s.starts_at)} to {formatTime(s.ends_at)}{" "}
                            <span className="text-muted-foreground">· {modeLabel(s.mode)}</span>
                          </span>
                          <span className="flex items-center gap-2">
                            {s.booked ? (
                              <Badge
                                variant={s.appointment_status === "confirmed" ? "success" : "info"}
                              >
                                {s.appointment_status === "confirmed" ? "Booked" : "Requested"}
                              </Badge>
                            ) : (
                              <Badge variant="outline">Open</Badge>
                            )}
                            {!s.booked && (
                              <Button
                                size="sm"
                                variant="ghost"
                                onClick={() => {
                                  clearError();
                                  setTarget(s);
                                }}
                                aria-label={`Remove ${day} ${formatTime(s.starts_at)}`}
                              >
                                <Trash2 aria-hidden="true" />
                                Remove
                              </Button>
                            )}
                          </span>
                        </li>
                      ))}
                    </ul>
                  </section>
                ))}
              </div>
            )}
          </SectionCard>
        )}
      </DataView>
      <ConfirmDialog
        open={target !== null}
        onOpenChange={(open) => !open && setTarget(null)}
        title="Remove this time?"
        description={
          target
            ? `${formatDay(target.starts_at)}, ${formatTime(target.starts_at)}. Students won't be able to request it.`
            : ""
        }
        confirmLabel="Remove time"
        cancelLabel="Keep it"
        pending={pending}
        error={error}
        onConfirm={remove}
      />
    </>
  );
}
