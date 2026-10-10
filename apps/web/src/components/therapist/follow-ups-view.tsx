"use client";

import { ClipboardCheck } from "lucide-react";
import Link from "next/link";
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
import { Textarea } from "@/components/ui/textarea";
import {
  FOLLOW_UP_KINDS,
  type CaseloadStudent,
  type FollowUp,
  type FollowUpKind,
} from "@/lib/api/therapist-schemas";
import { formatShortDate } from "@/lib/format";
import { useQuery } from "@/lib/hooks/use-query";
import { useTherapistApi } from "@/lib/hooks/use-therapist-api";
import { notify } from "@/lib/toast";

import { RequireVerified, SegmentedTabs } from "./shared";

const KIND_LABEL = Object.fromEntries(FOLLOW_UP_KINDS) as Record<string, string>;

/** Add a reminder. With `studentId` the student is fixed; otherwise the therapist picks one. */
export function NewFollowUpForm({
  studentId,
  sessionId,
  students,
  onCreated,
}: {
  studentId?: string;
  sessionId?: string;
  students?: CaseloadStudent[];
  onCreated: () => Promise<void>;
}) {
  const api = useTherapistApi();
  const [student, setStudent] = React.useState(studentId ?? students?.[0]?.student_id ?? "");
  const [kind, setKind] = React.useState<FollowUpKind>("check_in");
  const [due, setDue] = React.useState("");
  const [note, setNote] = React.useState("");
  const [formError, setFormError] = React.useState<string>();
  const { pending, error, run } = useSubmit();
  const formId = React.useId();

  function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!student) {
      setFormError("Choose a student.");
      return;
    }
    if (!due) {
      setFormError("Choose a due date.");
      return;
    }
    setFormError(undefined);
    void run(async () => {
      await api.createFollowUp({
        student_id: student,
        kind,
        due_on: due,
        note: note.trim() || undefined,
        session_id: sessionId,
      });
      notify.success("Follow-up added");
      setDue("");
      setNote("");
      await onCreated();
    }, "We couldn't add that follow-up. Check the date is within the next year.");
  }

  return (
    <form onSubmit={submit} className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4" noValidate>
      {studentId === undefined && (
        <div className="space-y-2">
          <Label htmlFor={`${formId}-student`}>Student</Label>
          <NativeSelect
            id={`${formId}-student`}
            value={student}
            onChange={(e) => setStudent(e.target.value)}
          >
            {(students ?? []).map((s) => (
              <option key={s.student_id} value={s.student_id}>
                {s.full_name}
              </option>
            ))}
          </NativeSelect>
        </div>
      )}
      <div className="space-y-2">
        <Label htmlFor={`${formId}-kind`}>What</Label>
        <NativeSelect
          id={`${formId}-kind`}
          value={kind}
          onChange={(e) => setKind(e.target.value as FollowUpKind)}
        >
          {FOLLOW_UP_KINDS.map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </NativeSelect>
      </div>
      <div className="space-y-2">
        <Label htmlFor={`${formId}-due`}>Due on</Label>
        <Input
          id={`${formId}-due`}
          type="date"
          value={due}
          onChange={(e) => setDue(e.target.value)}
        />
      </div>
      <div className="space-y-2 sm:col-span-2 lg:col-span-4">
        <Label htmlFor={`${formId}-note`}>Reminder for yourself (optional)</Label>
        <Textarea
          id={`${formId}-note`}
          value={note}
          onChange={(e) => setNote(e.target.value)}
          maxLength={1000}
          rows={2}
          aria-describedby={`${formId}-hint`}
        />
        <p id={`${formId}-hint`} className="text-sm text-muted-foreground">
          Only you can see this. The student never does.
        </p>
      </div>
      <div className="space-y-3 sm:col-span-2 lg:col-span-4">
        {formError && (
          <p role="alert" className="text-sm text-destructive">
            {formError}
          </p>
        )}
        {error && <InlineAlert tone="destructive">{error}</InlineAlert>}
        <SaveButton pending={pending}>Add follow-up</SaveButton>
      </div>
    </form>
  );
}

export function FollowUpRow({
  f,
  onChanged,
  showStudent = true,
}: {
  f: FollowUp;
  onChanged: () => Promise<void>;
  showStudent?: boolean;
}) {
  const api = useTherapistApi();
  const { pending, error, run } = useSubmit();

  function set(status: "done" | "open" | "cancelled") {
    void run(async () => {
      await api.updateFollowUp(f.id, { status });
      await onChanged();
    }, "We couldn't update that follow-up.");
  }

  return (
    <li className="flex flex-wrap items-start justify-between gap-3 py-4">
      <div className="min-w-0 space-y-1">
        <p className="font-medium">
          {KIND_LABEL[f.kind] ?? f.kind}
          {showStudent && (
            <>
              {" · "}
              <Link
                href={`/therapist/students/${f.student_id}`}
                className="underline underline-offset-4"
              >
                {f.student_name}
              </Link>
            </>
          )}
        </p>
        <p className="text-sm text-muted-foreground">Due {formatShortDate(f.due_on)}</p>
        {f.note && <p className="text-sm break-words">{f.note}</p>}
        {error && (
          <p role="alert" className="text-sm text-destructive">
            {error}
          </p>
        )}
      </div>
      <div className="flex flex-wrap items-center gap-2">
        {f.status === "open" && f.overdue && <Badge variant="warning">Overdue</Badge>}
        {f.status === "done" && <Badge variant="success">Done</Badge>}
        {f.status === "cancelled" && <Badge variant="outline">Cancelled</Badge>}
        {f.status === "open" ? (
          <>
            <Button size="sm" disabled={pending} onClick={() => set("done")}>
              Mark done
            </Button>
            <Button size="sm" variant="ghost" disabled={pending} onClick={() => set("cancelled")}>
              Cancel
            </Button>
          </>
        ) : (
          <Button size="sm" variant="outline" disabled={pending} onClick={() => set("open")}>
            Reopen
          </Button>
        )}
      </div>
    </li>
  );
}

type Filter = "open" | "done";

function FollowUpsBody() {
  const api = useTherapistApi();
  const students = useQuery("t-students", () => api.students());
  const [filter, setFilter] = React.useState<Filter>("open");
  const rows = useQuery(`t-follow-ups-${filter}`, () => api.followUps(filter));

  return (
    <>
      <DataView query={students} skeleton={null}>
        {(list) =>
          list.length === 0 ? null : (
            <SectionCard
              title="Add a follow-up"
              description="A private reminder about one of your students."
            >
              <NewFollowUpForm students={list} onCreated={rows.reload} />
            </SectionCard>
          )
        }
      </DataView>
      <SegmentedTabs
        label="Show"
        value={filter}
        onChange={setFilter}
        options={[
          { value: "open", label: "Open" },
          { value: "done", label: "Done" },
        ]}
      />
      <DataView query={rows}>
        {(list) =>
          list.length === 0 ? (
            <EmptyState
              icon={ClipboardCheck}
              title={filter === "open" ? "Nothing to follow up" : "Nothing completed yet"}
              description={
                filter === "open" ? "Reminders you set for your students appear here." : undefined
              }
            />
          ) : (
            <SectionCard title={filter === "open" ? "Open" : "Done"}>
              <ul className="divide-y">
                {list.map((f) => (
                  <FollowUpRow key={f.id} f={f} onChanged={rows.reload} />
                ))}
              </ul>
            </SectionCard>
          )
        }
      </DataView>
    </>
  );
}

export function FollowUpsView() {
  return (
    <>
      <PageHeader
        title="Follow-ups"
        description="Private reminders about students on your care team."
      />
      <RequireVerified>
        <FollowUpsBody />
      </RequireVerified>
    </>
  );
}
