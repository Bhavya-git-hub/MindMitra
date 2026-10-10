"use client";

import { Lock, NotebookPen } from "lucide-react";
import Link from "next/link";
import * as React from "react";

import { SectionCard } from "@/components/cards/section-card";
import { PageHeader } from "@/components/layout/page-header";
import { EmptyState } from "@/components/states/empty-state";
import { InlineAlert } from "@/components/states/inline-alert";
import { DataView } from "@/components/student/data-view";
import { SaveButton, useSubmit } from "@/components/student/form-bits";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import type { TherapySession } from "@/lib/api/therapist-schemas";
import { formatDateTime, formatDuration, modeLabel, titleCase } from "@/lib/format";
import { useQuery } from "@/lib/hooks/use-query";
import { useTherapistApi } from "@/lib/hooks/use-therapist-api";
import { notify } from "@/lib/toast";

import { NewFollowUpForm } from "./follow-ups-view";
import { ConfirmDialog, RequireVerified, SegmentedTabs } from "./shared";

const MAX_NOTE = 20_000;

const SESSION_VARIANT: Record<string, "success" | "info" | "outline" | "warning"> = {
  completed: "success",
  in_progress: "info",
  abandoned: "outline",
  scheduled: "outline",
};

function SessionRow({ s }: { s: TherapySession }) {
  return (
    <li className="flex flex-wrap items-center justify-between gap-3 py-4">
      <div className="space-y-1">
        <p className="font-medium">
          <Link href={`/therapist/sessions/${s.id}`} className="underline-offset-4 hover:underline">
            {s.student_name}
          </Link>
        </p>
        <p className="text-sm text-muted-foreground">
          {formatDateTime(s.scheduled_start)} · {modeLabel(s.mode)}
          {s.duration_minutes !== null ? ` · ${formatDuration(s.duration_minutes)}` : ""}
        </p>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <Badge variant={SESSION_VARIANT[s.status] ?? "outline"}>{titleCase(s.status)}</Badge>
        <Badge variant={s.has_note ? "secondary" : "outline"}>
          {s.has_note ? "Note written" : "No note yet"}
        </Badge>
        <Button asChild size="sm" variant="outline">
          <Link href={`/therapist/sessions/${s.id}`}>
            {s.status === "in_progress" ? "Continue" : "Open"}
          </Link>
        </Button>
      </div>
    </li>
  );
}

function SessionsBody() {
  const api = useTherapistApi();
  const [filter, setFilter] = React.useState<"all" | "in_progress" | "completed">("all");
  const rows = useQuery(`t-sessions-${filter}`, () =>
    api.sessions(filter === "all" ? undefined : filter),
  );
  return (
    <>
      <SegmentedTabs
        label="Show"
        value={filter}
        onChange={setFilter}
        options={[
          { value: "all", label: "All" },
          { value: "in_progress", label: "In progress" },
          { value: "completed", label: "Completed" },
        ]}
      />
      <DataView query={rows}>
        {(list) =>
          list.length === 0 ? (
            <EmptyState
              icon={NotebookPen}
              title="No sessions yet"
              description="Start a session from a confirmed appointment when it's time."
              action={
                <Button asChild variant="outline">
                  <Link href="/therapist/appointments">Appointments</Link>
                </Button>
              }
            />
          ) : (
            <SectionCard title="Sessions">
              <ul className="divide-y">
                {list.map((s) => (
                  <SessionRow key={s.id} s={s} />
                ))}
              </ul>
            </SectionCard>
          )
        }
      </DataView>
    </>
  );
}

export function SessionsView() {
  return (
    <>
      <PageHeader
        title="Sessions"
        description="Sessions you've run, and the private notes you've written about them."
      />
      <RequireVerified>
        <SessionsBody />
      </RequireVerified>
    </>
  );
}

// ---- one session: close it, write the note ---------------------------------------------------

function NoteEditor({ session }: { session: TherapySession }) {
  const api = useTherapistApi();
  const note = useQuery(`t-note-${session.id}`, () => api.note(session.id));
  return (
    <DataView query={note}>
      {(current) => <NoteForm session={session} current={current} onSaved={note.reload} />}
    </DataView>
  );
}

function NoteForm({
  session,
  current,
  onSaved,
}: {
  session: TherapySession;
  current: Awaited<ReturnType<ReturnType<typeof useTherapistApi>["note"]>>;
  onSaved: () => Promise<void>;
}) {
  const api = useTherapistApi();
  const saved = current?.body ?? "";
  const [text, setText] = React.useState(saved);
  const [viewing, setViewing] = React.useState<number | null>(null);
  const [old, setOld] = React.useState<string | null>(null);
  const [formError, setFormError] = React.useState<string>();
  const { pending, error, run } = useSubmit();
  const dirty = text !== saved;

  function submit(event: React.FormEvent) {
    event.preventDefault();
    if (text.trim() === "") {
      setFormError("Write something before saving.");
      return;
    }
    setFormError(undefined);
    void run(async () => {
      await api.saveNote(session.id, text);
      notify.success("Note saved", "A new version was kept. Earlier versions are never changed.");
      await onSaved();
    }, "We couldn't save your note. Your text is still here, so please try again.");
  }

  function view(version: number) {
    void run(async () => {
      const found = await api.note(session.id, version);
      setViewing(version);
      setOld(found?.body ?? "");
    }, "We couldn't open that version.");
  }

  return (
    <SectionCard
      title="Session note"
      description={
        current
          ? `Version ${current.version}, saved ${formatDateTime(current.written_at)}.`
          : "Nothing written yet."
      }
    >
      <div className="space-y-4">
        <InlineAlert tone="info" title="Only you can read this">
          <span className="inline-flex items-center gap-1">
            <Lock className="size-3.5" aria-hidden="true" />
            Notes are never shown to the student, teachers or administrators, and the audit log
            records that a note was opened but never what it says.
          </span>
        </InlineAlert>
        {viewing !== null && old !== null ? (
          <div className="space-y-3">
            <p className="text-sm font-medium">Version {viewing} (read only)</p>
            <p className="rounded-lg border bg-muted/40 p-3 break-words whitespace-pre-wrap">
              {old}
            </p>
            <Button
              variant="outline"
              onClick={() => {
                setViewing(null);
                setOld(null);
              }}
            >
              Back to the latest version
            </Button>
          </div>
        ) : (
          <form onSubmit={submit} className="space-y-3" noValidate>
            <Label htmlFor="note-body">Your note</Label>
            <Textarea
              id="note-body"
              value={text}
              onChange={(e) => setText(e.target.value)}
              maxLength={MAX_NOTE}
              rows={14}
              aria-invalid={formError ? true : undefined}
              aria-describedby="note-hint"
            />
            <p id="note-hint" className="text-sm text-muted-foreground">
              {text.length.toLocaleString()} / {MAX_NOTE.toLocaleString()} characters.{" "}
              {dirty ? "You have unsaved changes." : ""}
            </p>
            {formError && (
              <p role="alert" className="text-sm text-destructive">
                {formError}
              </p>
            )}
            {error && <InlineAlert tone="destructive">{error}</InlineAlert>}
            <SaveButton pending={pending} disabled={pending || !dirty}>
              Save note
            </SaveButton>
          </form>
        )}
        {current && current.versions.length > 1 && (
          <div>
            <h3 className="mb-2 text-sm font-medium">Earlier versions</h3>
            <ul className="flex flex-wrap gap-2">
              {current.versions
                .filter((v) => v.version !== current.version)
                .map((v) => (
                  <li key={v.version}>
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() => view(v.version)}
                      aria-label={`View version ${v.version}, saved ${formatDateTime(v.written_at)}`}
                    >
                      Version {v.version}
                    </Button>
                  </li>
                ))}
            </ul>
          </div>
        )}
      </div>
    </SectionCard>
  );
}

function SessionDetail({
  session,
  onChanged,
}: {
  session: TherapySession;
  onChanged: () => Promise<void>;
}) {
  const api = useTherapistApi();
  const [closing, setClosing] = React.useState<"completed" | "abandoned" | null>(null);
  const { pending, error, run, clearError } = useSubmit();

  function close() {
    if (!closing) return;
    const to = closing;
    void run(async () => {
      await api.finishSession(session.id, to);
      notify.success(to === "completed" ? "Session completed" : "Session closed");
      setClosing(null);
      await onChanged();
    }, "We couldn't close that session.");
  }

  return (
    <>
      <PageHeader
        title={`Session with ${session.student_name}`}
        description={`${formatDateTime(session.scheduled_start)} · ${modeLabel(session.mode)}`}
        actions={
          <>
            <Badge variant={SESSION_VARIANT[session.status] ?? "outline"}>
              {titleCase(session.status)}
            </Badge>
            <Button asChild variant="ghost">
              <Link href="/therapist/sessions">All sessions</Link>
            </Button>
          </>
        }
      />
      {session.status === "in_progress" && (
        <SectionCard title="This session is in progress">
          <div className="flex flex-wrap gap-2">
            <Button
              onClick={() => {
                clearError();
                setClosing("completed");
              }}
            >
              Complete session
            </Button>
            <Button
              variant="outline"
              onClick={() => {
                clearError();
                setClosing("abandoned");
              }}
            >
              Stop without completing
            </Button>
          </div>
        </SectionCard>
      )}
      <NoteEditor session={session} />
      <SectionCard
        title="Follow up after this session"
        description="A private reminder tied to this session."
      >
        <NewFollowUpForm
          studentId={session.student_id}
          sessionId={session.id}
          onCreated={async () => undefined}
        />
        <p className="mt-3 text-sm">
          <Link href="/therapist/follow-ups" className="underline underline-offset-4">
            See all follow-ups
          </Link>
        </p>
      </SectionCard>
      <ConfirmDialog
        open={closing !== null}
        onOpenChange={(open) => !open && setClosing(null)}
        title={closing === "completed" ? "Complete this session?" : "Stop without completing?"}
        description={
          closing === "completed"
            ? "The appointment is marked as completed. You can still write and update your note."
            : "The session is closed and the appointment stays as it was."
        }
        confirmLabel={closing === "completed" ? "Complete session" : "Stop session"}
        cancelLabel="Go back"
        pending={pending}
        error={error}
        onConfirm={close}
      />
    </>
  );
}

function SessionBody({ id }: { id: string }) {
  const api = useTherapistApi();
  const sessions = useQuery("t-sessions-detail", () => api.sessions());
  return (
    <DataView query={sessions}>
      {(list) => {
        const session = list.find((s) => s.id === id);
        if (!session) {
          return (
            <EmptyState
              icon={NotebookPen}
              title="We can't find that session"
              description="It may belong to someone else, or no longer be on your care team."
              action={
                <Button asChild variant="outline">
                  <Link href="/therapist/sessions">All sessions</Link>
                </Button>
              }
            />
          );
        }
        return <SessionDetail session={session} onChanged={sessions.reload} />;
      }}
    </DataView>
  );
}

export function SessionDetailView({ id }: { id: string }) {
  return (
    <RequireVerified>
      <SessionBody id={id} />
    </RequireVerified>
  );
}
