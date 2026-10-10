"use client";

import { Inbox } from "lucide-react";
import * as React from "react";

import { SectionCard } from "@/components/cards/section-card";
import { PageHeader } from "@/components/layout/page-header";
import { EmptyState } from "@/components/states/empty-state";
import { InlineAlert } from "@/components/states/inline-alert";
import { DataView } from "@/components/student/data-view";
import { useSubmit } from "@/components/student/form-bits";
import { SegmentedTabs } from "@/components/therapist/shared";
import { Button } from "@/components/ui/button";
import type { SupportRequest } from "@/lib/api/teacher-schemas";
import { formatDateTime } from "@/lib/format";
import { useQuery } from "@/lib/hooks/use-query";
import { useTeacherApi } from "@/lib/hooks/use-teacher-api";

import { PrivacyNote, REQUEST_STATUS_VARIANT, StatusBadge } from "./shared";

function RequestCard({ r, onChanged }: { r: SupportRequest; onChanged: () => Promise<void> }) {
  const api = useTeacherApi();
  const { pending, error, run } = useSubmit();
  function act(action: "acknowledge" | "close") {
    void run(async () => {
      if (action === "acknowledge") await api.acknowledgeRequest(r.id);
      else await api.closeRequest(r.id);
      await onChanged();
    }, "We couldn't update that request.");
  }
  const live = r.status === "open" || r.status === "acknowledged";
  return (
    <li className="space-y-3 rounded-xl border bg-card p-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="space-y-1">
          <h3 className="font-medium">
            {r.student_name} · {r.topic_label}
          </h3>
          <p className="text-sm text-muted-foreground">
            {r.course_code} {r.course_title} · {formatDateTime(r.created_at)}
          </p>
        </div>
        <StatusBadge status={r.status} label={r.status_label} variants={REQUEST_STATUS_VARIANT} />
      </div>
      {r.message && <p className="break-words whitespace-pre-line">{r.message}</p>}
      {error && <InlineAlert tone="destructive">{error}</InlineAlert>}
      {live && (
        <div className="flex flex-wrap gap-2">
          {r.status === "open" && (
            <Button size="sm" disabled={pending} onClick={() => act("acknowledge")}>
              I&apos;ve seen this
            </Button>
          )}
          <Button size="sm" variant="outline" disabled={pending} onClick={() => act("close")}>
            Mark as done
          </Button>
        </div>
      )}
    </li>
  );
}

export function SupportRequestsView() {
  const api = useTeacherApi();
  const [show, setShow] = React.useState<"live" | "closed">("live");
  const rows = useQuery(`teacher-requests-${show}`, () =>
    api.supportRequests(show === "closed" ? "closed" : undefined),
  );
  return (
    <>
      <PageHeader
        title="Student requests"
        description="Students who have chosen to ask you for help. Reply to them in person or through your usual channel."
      />
      <PrivacyNote>
        You see only the name and message the student chose to send. Nothing else about them comes
        with it.
      </PrivacyNote>
      <SegmentedTabs
        label="Show"
        value={show}
        onChange={setShow}
        options={[
          { value: "live", label: "Waiting" },
          { value: "closed", label: "Done" },
        ]}
      />
      <DataView query={rows}>
        {(list) =>
          list.length === 0 ? (
            <EmptyState
              icon={Inbox}
              title={show === "live" ? "Nothing waiting" : "Nothing here yet"}
              description={
                show === "live" ? "When a student asks you for help, it shows up here." : undefined
              }
            />
          ) : (
            <SectionCard title={show === "live" ? "Waiting for you" : "Done"}>
              <ul className="space-y-4">
                {list.map((r) => (
                  <RequestCard key={r.id} r={r} onChanged={rows.reload} />
                ))}
              </ul>
            </SectionCard>
          )
        }
      </DataView>
    </>
  );
}
