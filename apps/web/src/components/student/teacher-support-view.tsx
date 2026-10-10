"use client";

import { MessageSquareHeart } from "lucide-react";
import * as React from "react";

import { SectionCard } from "@/components/cards/section-card";
import { PageHeader } from "@/components/layout/page-header";
import { EmptyState } from "@/components/states/empty-state";
import { InlineAlert } from "@/components/states/inline-alert";
import { DataView } from "@/components/student/data-view";
import { NativeSelect, SaveButton, useSubmit } from "@/components/student/form-bits";
import { REQUEST_STATUS_VARIANT, StatusBadge } from "@/components/teacher/shared";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { SUPPORT_TOPICS, type CourseOption } from "@/lib/api/teacher-schemas";
import { formatDateTime } from "@/lib/format";
import { useQuery } from "@/lib/hooks/use-query";
import { useTeacherApi } from "@/lib/hooks/use-teacher-api";
import { notify } from "@/lib/toast";

function AskForm({ courses, onSent }: { courses: CourseOption[]; onSent: () => Promise<void> }) {
  const api = useTeacherApi();
  const [courseId, setCourseId] = React.useState(courses.length === 1 ? courses[0]!.course_id : "");
  const teachers = courses.find((c) => c.course_id === courseId)?.teachers ?? [];
  const [teacherId, setTeacherId] = React.useState("");
  const [topic, setTopic] = React.useState("");
  const [message, setMessage] = React.useState("");
  const [errors, setErrors] = React.useState<Record<string, string>>({});
  const { pending, error, run } = useSubmit();

  function submit(event: React.FormEvent) {
    event.preventDefault();
    const found: Record<string, string> = {};
    if (!courseId) found.course = "Choose a class.";
    if (!teacherId) found.teacher = "Choose a teacher.";
    if (!topic) found.topic = "Choose what you would like help with.";
    if (message.length > 600) found.message = "Please keep your message under 600 characters.";
    setErrors(found);
    if (Object.keys(found).length > 0) return;
    void run(async () => {
      await api.askTeacher({
        course_id: courseId,
        teacher_id: teacherId,
        topic,
        message: message.trim() || undefined,
      });
      notify.success("Sent. Your teacher will see it soon.");
      setTopic("");
      setMessage("");
      setTeacherId("");
      await onSent();
    }, "We couldn't send that.");
  }

  const bad = (name: string) => (errors[name] ? { "aria-invalid": true as const } : {});
  const note = (name: string) =>
    errors[name] ? (
      <p role="alert" className="text-sm text-destructive">
        {errors[name]}
      </p>
    ) : null;

  return (
    <form onSubmit={submit} noValidate className="max-w-xl space-y-5">
      <div className="space-y-2">
        <Label htmlFor="ts-course">Class</Label>
        <NativeSelect
          id="ts-course"
          value={courseId}
          {...bad("course")}
          onChange={(e) => {
            setCourseId(e.target.value);
            setTeacherId("");
          }}
        >
          <option value="">Choose…</option>
          {courses.map((c) => (
            <option key={c.course_id} value={c.course_id}>
              {c.code} {c.title}
            </option>
          ))}
        </NativeSelect>
        {note("course")}
      </div>
      <div className="space-y-2">
        <Label htmlFor="ts-teacher">Teacher</Label>
        <NativeSelect
          id="ts-teacher"
          value={teacherId}
          disabled={!courseId}
          {...bad("teacher")}
          onChange={(e) => setTeacherId(e.target.value)}
        >
          <option value="">{courseId ? "Choose…" : "Choose a class first"}</option>
          {teachers.map((t) => (
            <option key={t.teacher_id} value={t.teacher_id}>
              {t.name}
              {t.title ? `, ${t.title}` : ""}
            </option>
          ))}
        </NativeSelect>
        {note("teacher")}
      </div>
      <div className="space-y-2">
        <Label htmlFor="ts-topic">What would help?</Label>
        <NativeSelect
          id="ts-topic"
          value={topic}
          {...bad("topic")}
          onChange={(e) => setTopic(e.target.value)}
        >
          <option value="">Choose…</option>
          {SUPPORT_TOPICS.map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </NativeSelect>
        {note("topic")}
      </div>
      <div className="space-y-2">
        <Label htmlFor="ts-message">A few words for them (optional)</Label>
        <Textarea
          id="ts-message"
          rows={4}
          value={message}
          {...bad("message")}
          onChange={(e) => setMessage(e.target.value)}
          aria-describedby="ts-message-help"
        />
        <p id="ts-message-help" className="text-sm text-muted-foreground">
          Share only what you want them to know. You don&apos;t need to explain everything.
        </p>
        {note("message")}
      </div>
      {error && <InlineAlert tone="destructive">{error}</InlineAlert>}
      <SaveButton pending={pending}>Send to my teacher</SaveButton>
    </form>
  );
}

export function TeacherSupportView() {
  const api = useTeacherApi();
  const courses = useQuery("my-teacher-options", () => api.myCourses());
  const requests = useQuery("my-teacher-requests", () => api.myRequests());
  const withdraw = useSubmit();

  return (
    <>
      <PageHeader
        title="Ask a teacher"
        description="If something in a class is hard, you can ask one of your own teachers for help."
      />
      <InlineAlert tone="info" title="What your teacher sees">
        Your teacher sees your name, which class it is about and the message you write. They can
        never see your check-ins, journal, conversations or anything else. You can withdraw a
        request at any time.
      </InlineAlert>

      <SectionCard title="New request">
        <DataView query={courses}>
          {(list) =>
            list.length === 0 ? (
              <EmptyState
                icon={MessageSquareHeart}
                title="No classes found"
                description="Once you are enrolled in a class, you can ask its teacher for help here."
              />
            ) : (
              <AskForm courses={list} onSent={requests.reload} />
            )
          }
        </DataView>
      </SectionCard>

      <SectionCard title="Your requests">
        <DataView query={requests}>
          {(list) =>
            list.length === 0 ? (
              <p className="text-sm text-muted-foreground">You haven&apos;t sent any requests.</p>
            ) : (
              <ul className="divide-y">
                {list.map((r) => (
                  <li key={r.id} className="space-y-2 py-4">
                    <div className="flex flex-wrap items-start justify-between gap-2">
                      <div>
                        <p className="font-medium">
                          {r.topic_label} · {r.teacher_name}
                        </p>
                        <p className="text-sm text-muted-foreground">
                          {r.course_code} {r.course_title} · {formatDateTime(r.created_at)}
                        </p>
                      </div>
                      <StatusBadge
                        status={r.status}
                        label={r.status_label}
                        variants={REQUEST_STATUS_VARIANT}
                      />
                    </div>
                    {r.message && <p className="text-sm break-words">{r.message}</p>}
                    {(r.status === "open" || r.status === "acknowledged") && (
                      <Button
                        size="sm"
                        variant="outline"
                        disabled={withdraw.pending}
                        onClick={() =>
                          void withdraw.run(async () => {
                            await api.withdrawRequest(r.id);
                            await requests.reload();
                          }, "We couldn't withdraw that request.")
                        }
                      >
                        Withdraw
                      </Button>
                    )}
                  </li>
                ))}
              </ul>
            )
          }
        </DataView>
        {withdraw.error && <InlineAlert tone="destructive">{withdraw.error}</InlineAlert>}
      </SectionCard>
    </>
  );
}
