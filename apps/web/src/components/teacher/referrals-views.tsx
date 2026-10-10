"use client";

import { HeartHandshake, Plus } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import * as React from "react";

import { SectionCard } from "@/components/cards/section-card";
import { PageHeader } from "@/components/layout/page-header";
import { EmptyState } from "@/components/states/empty-state";
import { InlineAlert } from "@/components/states/inline-alert";
import { DataView } from "@/components/student/data-view";
import { NativeSelect, SaveButton, useSubmit } from "@/components/student/form-bits";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { REFERRAL_CATEGORIES, REFERRAL_URGENCIES, type Referral } from "@/lib/api/teacher-schemas";
import { formatDateTime } from "@/lib/format";
import { useQuery } from "@/lib/hooks/use-query";
import { useTeacherApi } from "@/lib/hooks/use-teacher-api";
import { notify } from "@/lib/toast";

import { PrivacyNote, REFERRAL_STATUS_VARIANT, StatusBadge, URGENCY_VARIANT } from "./shared";

function ReferralRow({ r }: { r: Referral }) {
  return (
    <li className="flex flex-wrap items-start justify-between gap-3 py-4">
      <div className="space-y-1">
        <p className="font-medium">
          <Link href={`/teacher/referrals/${r.id}`} className="underline-offset-4 hover:underline">
            {r.student_name}
          </Link>{" "}
          · {r.category_label}
        </p>
        <p className="text-sm text-muted-foreground">
          {r.course_code} {r.course_title} · {formatDateTime(r.created_at)}
        </p>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <StatusBadge status={r.urgency} label={r.urgency_label} variants={URGENCY_VARIANT} />
        <StatusBadge status={r.status} label={r.status_label} variants={REFERRAL_STATUS_VARIANT} />
      </div>
    </li>
  );
}

export function ReferralsView() {
  const api = useTeacherApi();
  const referrals = useQuery("teacher-referrals", () => api.referrals());
  return (
    <>
      <PageHeader
        title="Referrals"
        description="Ask the wellbeing team to reach out to a student in one of your classes."
        actions={
          <Button asChild>
            <Link href="/teacher/referrals/new">
              <Plus aria-hidden="true" />
              New referral
            </Link>
          </Button>
        }
      />
      <PrivacyNote>
        Referrals are handled in confidence. You will see whether one has been received, is with
        someone, or is closed, and nothing about what happens next.
      </PrivacyNote>
      <DataView query={referrals}>
        {(list) =>
          list.length === 0 ? (
            <EmptyState
              icon={HeartHandshake}
              title="No referrals yet"
              description="If you are worried about a student, a referral is a gentle way to ask someone trained to get in touch."
            />
          ) : (
            <SectionCard title="Your referrals" description="Newest first.">
              <ul className="divide-y">
                {list.map((r) => (
                  <ReferralRow key={r.id} r={r} />
                ))}
              </ul>
            </SectionCard>
          )
        }
      </DataView>
    </>
  );
}

export function NewReferralView() {
  const api = useTeacherApi();
  const router = useRouter();
  const preselected = useSearchParams().get("class") ?? "";
  const classes = useQuery("teacher-classes", () => api.classes());
  const [courseId, setCourseId] = React.useState(preselected);
  const roster = useQuery(`teacher-roster-${courseId}`, async () =>
    courseId ? api.roster(courseId) : [],
  );
  const [studentId, setStudentId] = React.useState("");
  const [category, setCategory] = React.useState("");
  const [urgency, setUrgency] = React.useState("routine");
  const [note, setNote] = React.useState("");
  const [errors, setErrors] = React.useState<Record<string, string>>({});
  const { pending, error, run } = useSubmit();

  function submit(event: React.FormEvent) {
    event.preventDefault();
    const found: Record<string, string> = {};
    if (!courseId) found.course = "Choose a class.";
    if (!studentId) found.student = "Choose a student.";
    if (!category) found.category = "Choose what you have noticed.";
    if (note.length > 1000) found.note = "Please keep the note under 1,000 characters.";
    setErrors(found);
    if (Object.keys(found).length > 0) return;
    void run(async () => {
      const made = await api.createReferral({
        student_id: studentId,
        course_id: courseId,
        category,
        urgency,
        note: note.trim() || undefined,
      });
      notify.success("Referral sent to the wellbeing team");
      router.push(`/teacher/referrals/${made.id}`);
    }, "We couldn't send that referral.");
  }

  const field = (name: string) => (errors[name] ? { "aria-invalid": true as const } : {});
  const message = (name: string) =>
    errors[name] ? (
      <p role="alert" className="text-sm text-destructive">
        {errors[name]}
      </p>
    ) : null;

  return (
    <>
      <PageHeader
        title="Refer a student"
        description="Tell the wellbeing team what you have noticed. They decide how to reach out."
        actions={
          <Button asChild variant="ghost">
            <Link href="/teacher/referrals">Back to referrals</Link>
          </Button>
        }
      />
      <InlineAlert tone="info" title="Before you refer">
        A referral asks a person to get in touch. It is not a judgement or a diagnosis. In an
        emergency, call your local emergency number or campus security straight away.
      </InlineAlert>
      <DataView query={classes}>
        {(list) => (
          <form onSubmit={submit} noValidate className="max-w-xl space-y-5">
            <div className="space-y-2">
              <Label htmlFor="ref-class">Class</Label>
              <NativeSelect
                id="ref-class"
                value={courseId}
                {...field("course")}
                onChange={(e) => {
                  setCourseId(e.target.value);
                  setStudentId("");
                }}
              >
                <option value="">Choose…</option>
                {list.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.code} {c.title}
                  </option>
                ))}
              </NativeSelect>
              {message("course")}
            </div>
            <div className="space-y-2">
              <Label htmlFor="ref-student">Student</Label>
              <NativeSelect
                id="ref-student"
                value={studentId}
                disabled={!courseId}
                {...field("student")}
                onChange={(e) => setStudentId(e.target.value)}
              >
                <option value="">{courseId ? "Choose…" : "Choose a class first"}</option>
                {(roster.state.data ?? []).map((s) => (
                  <option key={s.student_id} value={s.student_id}>
                    {s.name}
                  </option>
                ))}
              </NativeSelect>
              {message("student")}
            </div>
            <div className="space-y-2">
              <Label htmlFor="ref-category">What have you noticed?</Label>
              <NativeSelect
                id="ref-category"
                value={category}
                {...field("category")}
                onChange={(e) => setCategory(e.target.value)}
              >
                <option value="">Choose…</option>
                {REFERRAL_CATEGORIES.map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </NativeSelect>
              {message("category")}
            </div>
            <div className="space-y-2">
              <Label htmlFor="ref-urgency">How soon?</Label>
              <NativeSelect
                id="ref-urgency"
                value={urgency}
                onChange={(e) => setUrgency(e.target.value)}
              >
                {REFERRAL_URGENCIES.map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </NativeSelect>
            </div>
            <div className="space-y-2">
              <Label htmlFor="ref-note">What you have seen (optional)</Label>
              <Textarea
                id="ref-note"
                rows={4}
                value={note}
                {...field("note")}
                onChange={(e) => setNote(e.target.value)}
                aria-describedby="ref-note-help"
              />
              <p id="ref-note-help" className="text-sm text-muted-foreground">
                Stick to what you observed, such as missed classes or a change in how they seem.
                Please leave out guesses about health or private circumstances.
              </p>
              {message("note")}
            </div>
            {error && <InlineAlert tone="destructive">{error}</InlineAlert>}
            <SaveButton pending={pending}>Send referral</SaveButton>
          </form>
        )}
      </DataView>
    </>
  );
}

export function ReferralDetailView({ id }: { id: string }) {
  const api = useTeacherApi();
  const referral = useQuery(`teacher-referral-${id}`, () => api.referral(id));
  return (
    <DataView query={referral}>
      {(r) => (
        <>
          <PageHeader
            title={`Referral for ${r.student_name}`}
            description={`${r.course_code} ${r.course_title} · sent ${formatDateTime(r.created_at)}`}
            actions={
              <Button asChild variant="ghost">
                <Link href="/teacher/referrals">All referrals</Link>
              </Button>
            }
          />
          <SectionCard
            title="Where it stands"
            action={
              <StatusBadge
                status={r.status}
                label={r.status_label}
                variants={REFERRAL_STATUS_VARIANT}
              />
            }
          >
            <p className="text-sm text-muted-foreground">{r.message}</p>
          </SectionCard>
          <SectionCard title="What you sent">
            <dl className="grid gap-3 text-sm sm:grid-cols-2">
              <div>
                <dt className="text-muted-foreground">What you noticed</dt>
                <dd>{r.category_label}</dd>
              </div>
              <div>
                <dt className="text-muted-foreground">How soon</dt>
                <dd>{r.urgency_label}</dd>
              </div>
              {r.note && (
                <div className="sm:col-span-2">
                  <dt className="text-muted-foreground">Your note</dt>
                  <dd className="whitespace-pre-line break-words">{r.note}</dd>
                </div>
              )}
            </dl>
          </SectionCard>
        </>
      )}
    </DataView>
  );
}
