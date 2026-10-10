"use client";

import { MessageCircle, Search, Users } from "lucide-react";
import Link from "next/link";
import * as React from "react";

import { SectionCard } from "@/components/cards/section-card";
import { PageHeader } from "@/components/layout/page-header";
import { EmptyState } from "@/components/states/empty-state";
import { InlineAlert } from "@/components/states/inline-alert";
import { statusLabel, statusVariant } from "@/components/student/care-views";
import { DataView } from "@/components/student/data-view";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import type { CaseloadStudent } from "@/lib/api/therapist-schemas";
import { formatDateTime, formatShortDate, modeLabel, titleCase } from "@/lib/format";
import { useQuery } from "@/lib/hooks/use-query";
import { useTherapistApi } from "@/lib/hooks/use-therapist-api";

import { RequireVerified } from "./shared";
import {
  AssessmentsPanel,
  NotShared,
  RecommendationsPanel,
  StudentFollowUps,
  TrendsPanel,
} from "./student-sections";

function StudentCard({ s }: { s: CaseloadStudent }) {
  return (
    <li className="flex h-full flex-col gap-3 rounded-xl border bg-card p-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <h3 className="font-medium">
          <Link
            href={`/therapist/students/${s.student_id}`}
            className="underline-offset-4 hover:underline"
          >
            {s.full_name}
          </Link>
        </h3>
        <div className="flex flex-wrap gap-1.5">
          {s.open_alerts > 0 && (
            <Badge variant="warning">
              {s.open_alerts} alert{s.open_alerts === 1 ? "" : "s"}
            </Badge>
          )}
          {s.open_follow_ups > 0 && (
            <Badge variant="info">
              {s.open_follow_ups} follow-up{s.open_follow_ups === 1 ? "" : "s"}
            </Badge>
          )}
        </div>
      </div>
      <p className="text-sm text-muted-foreground">
        Year {s.year_of_study} · {s.care_role === "primary" ? "Primary" : "Shared"} care since{" "}
        {formatShortDate(s.since)}
      </p>
      <p className="text-sm">
        {s.next_appointment_at
          ? `Next: ${formatDateTime(s.next_appointment_at)}`
          : "No appointment booked"}
        {s.last_session_at ? ` · Last session ${formatShortDate(s.last_session_at)}` : ""}
      </p>
      <p className="text-sm text-muted-foreground">
        {s.sharing.mood ? "Shares check-ins" : "Check-ins not shared"}
      </p>
      <div className="mt-auto flex gap-2 pt-1">
        <Button asChild size="sm" variant="outline">
          <Link href={`/therapist/students/${s.student_id}`}>Open</Link>
        </Button>
        <Button asChild size="sm" variant="ghost">
          <Link href={`/therapist/messages/${s.student_id}`}>
            <MessageCircle aria-hidden="true" />
            Message
          </Link>
        </Button>
      </div>
    </li>
  );
}

function StudentsBody() {
  const api = useTherapistApi();
  const students = useQuery("t-students", () => api.students());
  const [text, setText] = React.useState("");

  return (
    <DataView query={students}>
      {(list) => {
        const needle = text.trim().toLowerCase();
        const shown = list.filter((s) => !needle || s.full_name.toLowerCase().includes(needle));
        if (list.length === 0) {
          return (
            <EmptyState
              icon={Users}
              title="No students yet"
              description="A student joins your care team when you confirm their first appointment."
              action={
                <Button asChild variant="outline">
                  <Link href="/therapist/appointments">Appointment requests</Link>
                </Button>
              }
            />
          );
        }
        return (
          <>
            <form role="search" aria-label="Find a student" onSubmit={(e) => e.preventDefault()}>
              <div className="max-w-sm space-y-2">
                <Label htmlFor="student-search">Find a student</Label>
                <Input
                  id="student-search"
                  type="search"
                  value={text}
                  onChange={(e) => setText(e.target.value)}
                />
              </div>
            </form>
            <p role="status" className="text-sm text-muted-foreground">
              {shown.length} student{shown.length === 1 ? "" : "s"} shown
            </p>
            {shown.length === 0 ? (
              <EmptyState icon={Search} title="No one matches that name" />
            ) : (
              <ul className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
                {shown.map((s) => (
                  <StudentCard key={s.student_id} s={s} />
                ))}
              </ul>
            )}
          </>
        );
      }}
    </DataView>
  );
}

export function StudentsView() {
  return (
    <>
      <PageHeader
        title="My students"
        description="Students on your care team. You only ever see the people you're looking after."
      />
      <RequireVerified>
        <StudentsBody />
      </RequireVerified>
    </>
  );
}

function ProfileBody({ id }: { id: string }) {
  const api = useTherapistApi();
  const profile = useQuery(`t-student-${id}`, () => api.student(id));
  return (
    <DataView query={profile}>
      {(p) => {
        const name = p.preferred_name ?? p.full_name.split(" ")[0] ?? p.full_name;
        return (
          <>
            <PageHeader
              title={p.full_name}
              description={`${p.department} · Year ${p.year_of_study}${p.pronouns ? ` · ${p.pronouns}` : ""}`}
              actions={
                <>
                  <Button asChild variant="outline">
                    <Link href={`/therapist/messages/${p.student_id}`}>
                      <MessageCircle aria-hidden="true" />
                      Message
                    </Link>
                  </Button>
                  <Button asChild variant="ghost">
                    <Link href="/therapist/students">All students</Link>
                  </Button>
                </>
              }
            />
            <InlineAlert tone="info" title="What you can see">
              You&apos;re on {name}&apos;s care team since {formatShortDate(p.since)}.{" "}
              {p.sharing.mood
                ? `${name} shares their check-ins with you.`
                : `${name} hasn't chosen to share their check-ins.`}{" "}
              {p.sharing.assessments
                ? "Their wellbeing checks are shared too."
                : "Their wellbeing checks are not shared."}
            </InlineAlert>
            {(p.open_alerts > 0 || p.open_follow_ups > 0) && (
              <div className="flex flex-wrap gap-2">
                {p.open_alerts > 0 && (
                  <Button asChild variant="outline" size="sm">
                    <Link href="/therapist/alerts">
                      {p.open_alerts} open alert{p.open_alerts === 1 ? "" : "s"}
                    </Link>
                  </Button>
                )}
                {p.open_follow_ups > 0 && (
                  <Button asChild variant="outline" size="sm">
                    <Link href="/therapist/follow-ups">
                      {p.open_follow_ups} open follow-up{p.open_follow_ups === 1 ? "" : "s"}
                    </Link>
                  </Button>
                )}
              </div>
            )}
            <div className="grid gap-4 lg:grid-cols-2">
              <SectionCard title="Appointments with you">
                {p.upcoming_appointments.length === 0 ? (
                  <p className="text-sm text-muted-foreground">Nothing coming up.</p>
                ) : (
                  <ul className="divide-y">
                    {p.upcoming_appointments.map((a) => (
                      <li
                        key={a.id}
                        className="flex flex-wrap items-center justify-between gap-2 py-3"
                      >
                        <span>
                          {formatDateTime(a.starts_at)}
                          <span className="text-muted-foreground"> · {modeLabel(a.mode)}</span>
                        </span>
                        <Badge variant={statusVariant(a.status)}>{statusLabel(a.status)}</Badge>
                      </li>
                    ))}
                  </ul>
                )}
              </SectionCard>
              <SectionCard title="Recent sessions">
                {p.recent_sessions.length === 0 ? (
                  <p className="text-sm text-muted-foreground">No sessions yet.</p>
                ) : (
                  <ul className="divide-y">
                    {p.recent_sessions.map((s) => (
                      <li
                        key={s.id}
                        className="flex flex-wrap items-center justify-between gap-2 py-3"
                      >
                        <Link
                          href={`/therapist/sessions/${s.id}`}
                          className="underline underline-offset-4"
                        >
                          {formatShortDate(s.started_at)}
                        </Link>
                        <span className="flex items-center gap-2">
                          <Badge variant="outline">{titleCase(s.status)}</Badge>
                          {s.has_note && <Badge variant="secondary">Note written</Badge>}
                        </span>
                      </li>
                    ))}
                  </ul>
                )}
              </SectionCard>
            </div>
            {p.sharing.mood ? (
              <TrendsPanel studentId={p.student_id} name={name} />
            ) : (
              <SectionCard title="Check-in trends">
                <NotShared what="their check-ins" name={name} />
              </SectionCard>
            )}
            {p.sharing.assessments ? (
              <AssessmentsPanel studentId={p.student_id} />
            ) : (
              <SectionCard title="Wellbeing checks">
                <NotShared what="their wellbeing checks" name={name} />
              </SectionCard>
            )}
            <RecommendationsPanel studentId={p.student_id} name={name} />
            <StudentFollowUps studentId={p.student_id} />
            <p className="text-sm text-muted-foreground">{p.disclaimer}</p>
          </>
        );
      }}
    </DataView>
  );
}

export function StudentProfileView({ id }: { id: string }) {
  return (
    <RequireVerified>
      <ProfileBody id={id} />
    </RequireVerified>
  );
}
