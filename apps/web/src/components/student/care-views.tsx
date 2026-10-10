"use client";

import { CalendarDays, CalendarPlus, MessageCircle, Search } from "lucide-react";
import Link from "next/link";
import * as React from "react";

import { SectionCard } from "@/components/cards/section-card";
import { PageHeader } from "@/components/layout/page-header";
import { EmptyState } from "@/components/states/empty-state";
import { InlineAlert } from "@/components/states/inline-alert";
import { DataView } from "@/components/student/data-view";
import { NativeSelect, SaveButton, useSubmit } from "@/components/student/form-bits";
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
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import type { Appointment, Slot, Therapist } from "@/lib/api/student-schemas";
import {
  formatDateTime,
  formatDay,
  formatDuration,
  formatTime,
  modeLabel,
  titleCase,
} from "@/lib/format";
import { useQuery } from "@/lib/hooks/use-query";
import { useStudentApi } from "@/lib/hooks/use-student-api";
import { notify } from "@/lib/toast";

const REASON_LIMIT = 500;

export function statusLabel(status: string): string {
  return status === "requested" ? "Waiting for confirmation" : titleCase(status);
}

export function statusVariant(status: string): "success" | "info" | "warning" | "outline" {
  if (status === "confirmed" || status === "completed") return "success";
  if (status === "requested") return "info";
  if (status === "cancelled" || status === "declined") return "outline";
  return "warning";
}

// ---- therapist search ---------------------------------------------------------------------------

function TherapistCard({ t }: { t: Therapist }) {
  return (
    <li className="flex h-full flex-col gap-3 rounded-xl border bg-card p-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <h3 className="font-medium">
          <Link href={`/student/therapists/${t.id}`} className="underline-offset-4 hover:underline">
            {t.full_name}
          </Link>
        </h3>
        {t.on_my_care_team && <Badge variant="success">Your care team</Badge>}
        {!t.accepting_new_students && !t.on_my_care_team && (
          <Badge variant="outline">Not taking new students</Badge>
        )}
      </div>
      {t.specialties.length > 0 && (
        <p className="flex flex-wrap gap-1.5">
          {t.specialties.map((s) => (
            <Badge key={s} variant="secondary">
              {s}
            </Badge>
          ))}
        </p>
      )}
      <p className="text-sm text-muted-foreground">
        {t.languages.length > 0 ? `Speaks ${t.languages.join(", ")}. ` : ""}
        {t.next_available_at
          ? `Next opening: ${formatDateTime(t.next_available_at)}.`
          : "No openings listed right now."}
      </p>
      <div className="mt-auto pt-1">
        <Button asChild size="sm" variant="outline">
          <Link href={`/student/therapists/${t.id}`}>View profile</Link>
        </Button>
      </div>
    </li>
  );
}

export function TherapistSearchView() {
  const api = useStudentApi();
  const all = useQuery("therapists", () => api.therapists());
  const [text, setText] = React.useState("");
  const [specialty, setSpecialty] = React.useState("");
  const [language, setLanguage] = React.useState("");
  const [acceptingOnly, setAcceptingOnly] = React.useState(true);

  return (
    <>
      <PageHeader
        title="Find a therapist"
        description="Therapists from your institution's counselling service. You choose who to see."
      />
      <DataView query={all}>
        {(therapists) => {
          const specialties = [...new Set(therapists.flatMap((t) => t.specialties))].sort();
          const languages = [...new Set(therapists.flatMap((t) => t.languages))].sort();
          const needle = text.trim().toLowerCase();
          const shown = therapists.filter(
            (t) =>
              (!needle || t.full_name.toLowerCase().includes(needle)) &&
              (!specialty || t.specialties.includes(specialty)) &&
              (!language || t.languages.includes(language)) &&
              (!acceptingOnly || t.accepting_new_students || t.on_my_care_team),
          );
          return (
            <>
              <form
                role="search"
                aria-label="Find a therapist"
                onSubmit={(e) => e.preventDefault()}
                className="grid gap-4 rounded-xl border bg-card p-4 sm:grid-cols-2 lg:grid-cols-4"
              >
                <div className="space-y-2">
                  <Label htmlFor="t-name">Name</Label>
                  <Input
                    id="t-name"
                    type="search"
                    value={text}
                    onChange={(e) => setText(e.target.value)}
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="t-specialty">Focus area</Label>
                  <NativeSelect
                    id="t-specialty"
                    value={specialty}
                    onChange={(e) => setSpecialty(e.target.value)}
                  >
                    <option value="">Any</option>
                    {specialties.map((s) => (
                      <option key={s} value={s}>
                        {s}
                      </option>
                    ))}
                  </NativeSelect>
                </div>
                <div className="space-y-2">
                  <Label htmlFor="t-language">Language</Label>
                  <NativeSelect
                    id="t-language"
                    value={language}
                    onChange={(e) => setLanguage(e.target.value)}
                  >
                    <option value="">Any</option>
                    {languages.map((l) => (
                      <option key={l} value={l}>
                        {l}
                      </option>
                    ))}
                  </NativeSelect>
                </div>
                <div className="flex items-end">
                  <label className="flex min-h-10 items-center gap-2 text-sm">
                    <input
                      type="checkbox"
                      checked={acceptingOnly}
                      onChange={(e) => setAcceptingOnly(e.target.checked)}
                      className="size-4 accent-[var(--primary)]"
                    />
                    Only show therapists taking new students
                  </label>
                </div>
              </form>
              <p role="status" className="text-sm text-muted-foreground">
                {shown.length} therapist{shown.length === 1 ? "" : "s"} shown
              </p>
              {shown.length === 0 ? (
                <EmptyState
                  icon={Search}
                  title="No one matches yet"
                  description="Try removing a filter. If you need to talk to someone right away, see urgent support."
                  action={
                    <Button asChild variant="outline">
                      <Link href="/student/emergency">Urgent support</Link>
                    </Button>
                  }
                />
              ) : (
                <ul className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
                  {shown.map((t) => (
                    <TherapistCard key={t.id} t={t} />
                  ))}
                </ul>
              )}
            </>
          );
        }}
      </DataView>
    </>
  );
}

// ---- therapist profile + booking ----------------------------------------------------------------

function BookingDialog({
  therapistName,
  slot,
  onClose,
  onBooked,
}: {
  therapistName: string;
  slot: Slot | null;
  onClose: () => void;
  onBooked: () => Promise<void>;
}) {
  const api = useStudentApi();
  const [reason, setReason] = React.useState("");
  const { pending, error, run, clearError } = useSubmit();

  function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!slot) return;
    void run(async () => {
      await api.bookAppointment(slot.id, reason.trim() || undefined);
      notify.success("Request sent", `${therapistName} will confirm your appointment.`);
      setReason("");
      onClose();
      await onBooked();
    }, "We couldn't book that time. It may have just been taken, so please pick another.");
  }

  return (
    <Dialog
      open={slot !== null}
      onOpenChange={(open) => {
        if (!open) {
          clearError();
          onClose();
        }
      }}
    >
      <DialogContent>
        <form onSubmit={submit} className="space-y-4" noValidate>
          <DialogHeader>
            <DialogTitle>Request this appointment</DialogTitle>
            <DialogDescription>
              {slot
                ? `${formatDay(slot.starts_at)}, ${formatTime(slot.starts_at)} to ${formatTime(slot.ends_at)} · ${modeLabel(slot.mode)} with ${therapistName}.`
                : ""}{" "}
              {therapistName} will confirm it. You can cancel until 2 hours before.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-2">
            <Label htmlFor="booking-reason">What would you like to talk about? (optional)</Label>
            <Textarea
              id="booking-reason"
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              maxLength={REASON_LIMIT}
              rows={3}
              aria-describedby="booking-reason-hint"
            />
            <p id="booking-reason-hint" className="text-sm text-muted-foreground">
              Only the therapist you&apos;re booking with will see this.
            </p>
          </div>
          {error && <InlineAlert tone="destructive">{error}</InlineAlert>}
          <DialogFooter>
            <Button type="button" variant="ghost" onClick={onClose}>
              Not now
            </Button>
            <SaveButton pending={pending}>Send request</SaveButton>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function groupByDay(slots: Slot[]): [string, Slot[]][] {
  const groups = new Map<string, Slot[]>();
  for (const slot of slots) {
    const day = formatDay(slot.starts_at);
    groups.set(day, [...(groups.get(day) ?? []), slot]);
  }
  return [...groups.entries()];
}

export function TherapistProfileView({ id }: { id: string }) {
  const api = useStudentApi();
  const profile = useQuery(`therapist-${id}`, () => api.therapist(id));
  const slots = useQuery(`therapist-slots-${id}`, () => api.therapistSlots(id));
  const [chosen, setChosen] = React.useState<Slot | null>(null);
  const [booked, setBooked] = React.useState(false);

  return (
    <DataView query={profile}>
      {(t) => (
        <>
          <PageHeader
            title={t.full_name}
            description={t.languages.length > 0 ? `Speaks ${t.languages.join(", ")}` : undefined}
            actions={
              <>
                {t.on_my_care_team && (
                  <Button asChild variant="outline">
                    <Link href={`/student/messages/${t.id}`}>
                      <MessageCircle aria-hidden="true" />
                      Message
                    </Link>
                  </Button>
                )}
                <Button asChild variant="ghost">
                  <Link href="/student/therapists">All therapists</Link>
                </Button>
              </>
            }
          />
          <SectionCard title="About">
            <div className="space-y-3">
              {t.bio ? <p>{t.bio}</p> : <p className="text-muted-foreground">No bio yet.</p>}
              {t.specialties.length > 0 && (
                <p className="flex flex-wrap gap-1.5">
                  {t.specialties.map((s) => (
                    <Badge key={s}>{s}</Badge>
                  ))}
                </p>
              )}
              {!t.accepting_new_students && !t.on_my_care_team && (
                <InlineAlert tone="warning">
                  This therapist isn&apos;t taking new students at the moment.
                </InlineAlert>
              )}
            </div>
          </SectionCard>
          <SectionCard
            title="Available times"
            description="Times are shown in your own time zone. Choosing one sends a request that the therapist confirms."
          >
            {booked && (
              <InlineAlert tone="success" title="Request sent" className="mb-4">
                <Link href="/student/appointments" className="underline underline-offset-4">
                  See your appointments
                </Link>
              </InlineAlert>
            )}
            <DataView
              query={slots}
              skeleton={<p className="text-sm text-muted-foreground">Loading times…</p>}
            >
              {(list) =>
                list.length === 0 ? (
                  <EmptyState
                    icon={CalendarDays}
                    title="No openings right now"
                    description="Check back soon, or look at another therapist."
                  />
                ) : (
                  <div className="space-y-5">
                    {groupByDay(list).map(([day, daySlots]) => (
                      <section key={day} aria-label={day}>
                        <h3 className="mb-2 font-medium">{day}</h3>
                        <ul className="flex flex-wrap gap-2">
                          {daySlots.map((s) => (
                            <li key={s.id}>
                              <Button
                                variant="outline"
                                onClick={() => setChosen(s)}
                                aria-label={`${day}, ${formatTime(s.starts_at)}, ${modeLabel(s.mode)}`}
                              >
                                <CalendarPlus aria-hidden="true" />
                                {formatTime(s.starts_at)}
                                <span className="text-muted-foreground">{modeLabel(s.mode)}</span>
                              </Button>
                            </li>
                          ))}
                        </ul>
                      </section>
                    ))}
                  </div>
                )
              }
            </DataView>
          </SectionCard>
          <BookingDialog
            therapistName={t.full_name}
            slot={chosen}
            onClose={() => setChosen(null)}
            onBooked={async () => {
              setBooked(true);
              await slots.reload();
            }}
          />
        </>
      )}
    </DataView>
  );
}

// ---- appointments -------------------------------------------------------------------------------

function AppointmentRow({ a, onCancel }: { a: Appointment; onCancel?: (a: Appointment) => void }) {
  const minutes = Math.round(
    (new Date(a.ends_at).getTime() - new Date(a.starts_at).getTime()) / 60_000,
  );
  return (
    <li className="flex flex-wrap items-center justify-between gap-3 py-4">
      <div className="space-y-1">
        <p className="font-medium">
          {formatDay(a.starts_at)}, {formatTime(a.starts_at)}
        </p>
        <p className="text-sm text-muted-foreground">
          With{" "}
          <Link
            href={`/student/therapists/${a.therapist_id}`}
            className="underline underline-offset-4"
          >
            {a.therapist_name}
          </Link>{" "}
          · {modeLabel(a.mode)} · {formatDuration(minutes)}
        </p>
        {a.reason && <p className="text-sm">&ldquo;{a.reason}&rdquo;</p>}
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <Badge variant={statusVariant(a.status)}>{statusLabel(a.status)}</Badge>
        {onCancel && a.can_cancel && (
          <Button size="sm" variant="outline" onClick={() => onCancel(a)}>
            Cancel
          </Button>
        )}
      </div>
    </li>
  );
}

export function AppointmentsView() {
  const api = useStudentApi();
  const upcomingQuery = useQuery("appointments-upcoming", () => api.appointments(true));
  const allQuery = useQuery("appointments-all", () => api.appointments());
  const [target, setTarget] = React.useState<Appointment | null>(null);
  const { pending, error, run } = useSubmit();

  function confirmCancel() {
    if (!target) return;
    const id = target.id;
    void run(async () => {
      await api.cancelAppointment(id);
      notify.success("Appointment cancelled");
      setTarget(null);
      await Promise.all([upcomingQuery.reload(), allQuery.reload()]);
    }, "We couldn't cancel that appointment. Please try again.");
  }

  return (
    <>
      <PageHeader
        title="Appointments"
        description="Your sessions with therapists."
        actions={
          <Button asChild>
            <Link href="/student/therapists">
              <CalendarPlus aria-hidden="true" />
              Book an appointment
            </Link>
          </Button>
        }
      />
      {error && <InlineAlert tone="destructive">{error}</InlineAlert>}
      <DataView query={upcomingQuery}>
        {(upcoming) => (
          <SectionCard title="Upcoming">
            {upcoming.length === 0 ? (
              <EmptyState
                icon={CalendarDays}
                title="Nothing booked"
                description="When you're ready, you can look through therapists and pick a time."
              />
            ) : (
              <ul className="divide-y">
                {upcoming.map((a) => (
                  <AppointmentRow key={a.id} a={a} onCancel={setTarget} />
                ))}
              </ul>
            )}
          </SectionCard>
        )}
      </DataView>
      <DataView query={allQuery} skeleton={null}>
        {(all) => {
          const upcomingIds = new Set(upcomingQuery.state.data?.map((a) => a.id) ?? []);
          const history = all.filter((a) => !upcomingIds.has(a.id));
          return (
            <SectionCard title="History">
              {history.length === 0 ? (
                <p className="text-sm text-muted-foreground">Past appointments will appear here.</p>
              ) : (
                <ul className="divide-y">
                  {history.map((a) => (
                    <AppointmentRow key={a.id} a={a} />
                  ))}
                </ul>
              )}
            </SectionCard>
          );
        }}
      </DataView>
      <AlertDialog open={target !== null} onOpenChange={(open) => !open && setTarget(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Cancel this appointment?</AlertDialogTitle>
            <AlertDialogDescription>
              {target
                ? `${formatDateTime(target.starts_at)} with ${target.therapist_name}. The time goes back to their calendar.`
                : ""}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Keep it</AlertDialogCancel>
            <AlertDialogAction
              disabled={pending}
              onClick={(e) => {
                e.preventDefault();
                confirmCancel();
              }}
            >
              Cancel appointment
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
}
