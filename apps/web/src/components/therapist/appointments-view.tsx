"use client";

import { CalendarDays } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import * as React from "react";

import { SectionCard } from "@/components/cards/section-card";
import { PageHeader } from "@/components/layout/page-header";
import { EmptyState } from "@/components/states/empty-state";
import { InlineAlert } from "@/components/states/inline-alert";
import { statusLabel, statusVariant } from "@/components/student/care-views";
import { DataView } from "@/components/student/data-view";
import { useSubmit } from "@/components/student/form-bits";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import type { AppointmentScope } from "@/lib/api/therapist-api";
import type { TherapistAppointment } from "@/lib/api/therapist-schemas";
import { formatDateTime, formatDuration, modeLabel, titleCase } from "@/lib/format";
import { useQuery } from "@/lib/hooks/use-query";
import { useTherapistApi } from "@/lib/hooks/use-therapist-api";
import { notify } from "@/lib/toast";

import { ConfirmDialog, RequireVerified, SegmentedTabs } from "./shared";

type Action = { appointment: TherapistAppointment; to: "cancelled" | "no_show" };

function minutesBetween(a: TherapistAppointment): number {
  return Math.round((new Date(a.ends_at).getTime() - new Date(a.starts_at).getTime()) / 60_000);
}

const TABS: { value: AppointmentScope; label: string }[] = [
  { value: "requests", label: "Requests" },
  { value: "upcoming", label: "Upcoming" },
  { value: "past", label: "Past" },
];

function Row({
  a,
  onConfirm,
  onAsk,
  onStart,
  busy,
}: {
  a: TherapistAppointment;
  onConfirm: (a: TherapistAppointment) => void;
  onAsk: (action: Action) => void;
  onStart: (a: TherapistAppointment) => void;
  busy: boolean;
}) {
  return (
    <li className="flex flex-wrap items-start justify-between gap-3 py-4">
      <div className="min-w-0 space-y-1">
        <p className="font-medium">{formatDateTime(a.starts_at)}</p>
        <p className="text-sm text-muted-foreground">
          <Link
            href={`/therapist/students/${a.student_id}`}
            className="underline underline-offset-4"
          >
            {a.student_name}
          </Link>{" "}
          · {modeLabel(a.mode)} · {formatDuration(minutesBetween(a))}
        </p>
        {a.reason && <p className="text-sm break-words">&ldquo;{a.reason}&rdquo;</p>}
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <Badge variant={statusVariant(a.status)}>
          {a.status === "requested" ? "Waiting for you" : statusLabel(a.status)}
        </Badge>
        {a.status === "requested" && (
          <>
            <Button size="sm" disabled={busy} onClick={() => onConfirm(a)}>
              Confirm
            </Button>
            <Button
              size="sm"
              variant="outline"
              disabled={busy}
              onClick={() => onAsk({ appointment: a, to: "cancelled" })}
            >
              Decline
            </Button>
          </>
        )}
        {a.status === "confirmed" && (
          <>
            {a.session_id ? (
              <Button asChild size="sm" variant="outline">
                <Link href={`/therapist/sessions/${a.session_id}`}>Open session</Link>
              </Button>
            ) : (
              a.can_start && (
                <Button size="sm" disabled={busy} onClick={() => onStart(a)}>
                  Start session
                </Button>
              )
            )}
            <Button
              size="sm"
              variant="outline"
              disabled={busy}
              onClick={() => onAsk({ appointment: a, to: "cancelled" })}
            >
              Cancel
            </Button>
            <Button
              size="sm"
              variant="ghost"
              disabled={busy}
              onClick={() => onAsk({ appointment: a, to: "no_show" })}
            >
              Didn&apos;t attend
            </Button>
          </>
        )}
        {a.status === "completed" && a.session_id && (
          <Button asChild size="sm" variant="outline">
            <Link href={`/therapist/sessions/${a.session_id}`}>Session and notes</Link>
          </Button>
        )}
      </div>
    </li>
  );
}

function AppointmentList({ scope }: { scope: AppointmentScope }) {
  const api = useTherapistApi();
  const router = useRouter();
  const rows = useQuery(`t-appointments-${scope}`, () => api.appointments(scope));
  const [action, setAction] = React.useState<Action | null>(null);
  const { pending, error, run, clearError } = useSubmit();

  const reload = rows.reload;

  function setStatus(a: TherapistAppointment, to: "confirmed" | "cancelled" | "no_show") {
    void run(async () => {
      await api.setAppointmentStatus(a.id, to);
      notify.success(
        to === "confirmed"
          ? "Appointment confirmed"
          : to === "cancelled"
            ? "Appointment cancelled"
            : "Marked as didn't attend",
        to === "confirmed" ? "The student has been told." : undefined,
      );
      setAction(null);
      await reload();
    }, "We couldn't update that appointment. It may have changed, so please refresh.");
  }

  function start(a: TherapistAppointment) {
    void run(async () => {
      const session = await api.startSession(a.id);
      router.push(`/therapist/sessions/${session.id}`);
    }, "We couldn't start that session.");
  }

  return (
    <>
      {error && !action && <InlineAlert tone="destructive">{error}</InlineAlert>}
      <DataView query={rows}>
        {(list) =>
          list.length === 0 ? (
            <EmptyState
              icon={CalendarDays}
              title={
                scope === "requests"
                  ? "No requests waiting"
                  : scope === "upcoming"
                    ? "Nothing confirmed ahead"
                    : "No past appointments"
              }
              description={
                scope === "requests"
                  ? "When a student asks for one of your times, it appears here."
                  : undefined
              }
            />
          ) : (
            <SectionCard title={titleCase(scope)}>
              <ul className="divide-y">
                {list.map((a) => (
                  <Row
                    key={a.id}
                    a={a}
                    busy={pending}
                    onConfirm={(x) => setStatus(x, "confirmed")}
                    onAsk={(x) => {
                      clearError();
                      setAction(x);
                    }}
                    onStart={start}
                  />
                ))}
              </ul>
            </SectionCard>
          )
        }
      </DataView>
      <ConfirmDialog
        open={action !== null}
        onOpenChange={(open) => !open && setAction(null)}
        title={
          action?.to === "no_show"
            ? "Mark as didn't attend?"
            : action?.appointment.status === "requested"
              ? "Decline this request?"
              : "Cancel this appointment?"
        }
        description={
          action
            ? action.to === "no_show"
              ? `${action.appointment.student_name}, ${formatDateTime(action.appointment.starts_at)}.`
              : `${action.appointment.student_name}, ${formatDateTime(action.appointment.starts_at)}. The student is told and the time goes back to your calendar.`
            : ""
        }
        confirmLabel={
          action?.to === "no_show"
            ? "Mark as didn't attend"
            : action?.appointment.status === "requested"
              ? "Decline request"
              : "Cancel appointment"
        }
        pending={pending}
        error={error}
        onConfirm={() => action && setStatus(action.appointment, action.to)}
      />
    </>
  );
}

export function AppointmentsView() {
  const [scope, setScope] = React.useState<AppointmentScope>("requests");
  return (
    <>
      <PageHeader
        title="Appointments"
        description="Answer requests, run sessions and look back at past ones."
        actions={
          <Button asChild variant="outline">
            <Link href="/therapist/availability">Availability</Link>
          </Button>
        }
      />
      <RequireVerified>
        <SegmentedTabs label="Show" value={scope} options={TABS} onChange={setScope} />
        <AppointmentList key={scope} scope={scope} />
      </RequireVerified>
    </>
  );
}
