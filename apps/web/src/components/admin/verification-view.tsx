"use client";

import { BadgeCheck } from "lucide-react";
import * as React from "react";

import { SectionCard } from "@/components/cards/section-card";
import { PageHeader } from "@/components/layout/page-header";
import { EmptyState } from "@/components/states/empty-state";
import { DataView } from "@/components/student/data-view";
import { useSubmit } from "@/components/student/form-bits";
import { SegmentedTabs, VerificationBadge } from "@/components/therapist/shared";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Input } from "@/components/ui/input";
import type { TherapistReview } from "@/lib/api/admin-schemas";
import { formatShortDate, titleCase } from "@/lib/format";
import { useAdminApi } from "@/lib/hooks/use-admin-api";
import { useQuery } from "@/lib/hooks/use-query";
import { notify } from "@/lib/toast";

import { Field, FormActions, FormDialog } from "./shared";

type Filter = "pending" | "verified" | "rejected" | "all";

function ReviewForm({
  therapist,
  onDone,
  onCancel,
}: {
  therapist: TherapistReview;
  onDone: () => void;
  onCancel: () => void;
}) {
  const api = useAdminApi();
  const [decision, setDecision] = React.useState<"verified" | "rejected">("verified");
  const [expires, setExpires] = React.useState(therapist.licence_expires_on ?? "");
  const [note, setNote] = React.useState(therapist.verification_note ?? "");
  const [errors, setErrors] = React.useState<Record<string, string>>({});
  const { pending, error, run } = useSubmit();

  function submit(event: React.FormEvent) {
    event.preventDefault();
    const found: Record<string, string> = {};
    if (note.length > 300) found.note = "Please keep the note under 300 characters.";
    if (decision === "rejected" && !note.trim())
      found.note = "Say briefly why, so the therapist knows what to fix.";
    setErrors(found);
    if (Object.keys(found).length > 0) return;
    void run(async () => {
      await api.reviewTherapist(therapist.id, {
        status: decision,
        note: note.trim() || undefined,
        licence_expires_on: decision === "verified" && expires ? expires : undefined,
      });
      notify.success(
        decision === "verified" ? "Therapist verified" : "Registration marked as not accepted",
      );
      onDone();
    }, "We couldn't save that decision.");
  }

  return (
    <form onSubmit={submit} noValidate className="space-y-4">
      <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm">
        <dt className="text-muted-foreground">Licence number</dt>
        <dd>{therapist.licence_number}</dd>
        <dt className="text-muted-foreground">Issued by</dt>
        <dd>{therapist.licence_body ?? "Not given"}</dd>
        <dt className="text-muted-foreground">Expires</dt>
        <dd>
          {therapist.licence_expires_on
            ? formatShortDate(therapist.licence_expires_on)
            : "Not given"}
        </dd>
      </dl>
      <SegmentedTabs
        label="Decision"
        value={decision}
        onChange={setDecision}
        options={[
          { value: "verified", label: "Verify" },
          { value: "rejected", label: "Do not accept" },
        ]}
      />
      {decision === "verified" && (
        <Field label="Licence expiry date" hint="Leave as it is if the date is already correct.">
          {(p) => (
            <Input
              {...p}
              type="date"
              value={expires}
              onChange={(e) => setExpires(e.target.value)}
            />
          )}
        </Field>
      )}
      <Field
        label={decision === "rejected" ? "Reason" : "Note (optional)"}
        hint="The therapist can read this. Keep it to the registration, nothing personal."
        error={errors.note}
      >
        {(p) => <Textarea {...p} rows={3} value={note} onChange={(e) => setNote(e.target.value)} />}
      </Field>
      <FormActions pending={pending} error={error} onCancel={onCancel} submit="Save decision" />
    </form>
  );
}

export function VerificationView() {
  const api = useAdminApi();
  const [filter, setFilter] = React.useState<Filter>("pending");
  const queue = useQuery(`admin-verification-${filter}`, () =>
    api.verificationQueue(filter === "all" ? undefined : filter),
  );
  const [reviewing, setReviewing] = React.useState<TherapistReview | null>(null);

  return (
    <>
      <PageHeader
        title="Therapist verification"
        description="Therapists can see students only after you have checked their professional registration."
      />
      <SegmentedTabs
        label="Show"
        value={filter}
        onChange={setFilter}
        options={[
          { value: "pending", label: "Waiting" },
          { value: "verified", label: "Verified" },
          { value: "rejected", label: "Not accepted" },
          { value: "all", label: "Everyone" },
        ]}
      />
      <DataView query={queue}>
        {(rows) =>
          rows.length === 0 ? (
            <EmptyState
              icon={BadgeCheck}
              title="Nobody here"
              description={
                filter === "pending"
                  ? "Every therapist has been reviewed."
                  : "No therapists match this filter."
              }
            />
          ) : (
            <SectionCard title={`${rows.length} therapist${rows.length === 1 ? "" : "s"}`}>
              <ul className="divide-y">
                {rows.map((t) => (
                  <li key={t.id} className="flex flex-wrap items-center justify-between gap-3 py-3">
                    <div className="min-w-0">
                      <p className="font-medium">{t.full_name}</p>
                      <p className="text-sm text-muted-foreground">
                        {t.email} · Licence {t.licence_number}
                        {t.licence_expires_on
                          ? ` · expires ${formatShortDate(t.licence_expires_on)}`
                          : ""}
                      </p>
                      {t.verification_note && (
                        <p className="text-sm text-muted-foreground">Note: {t.verification_note}</p>
                      )}
                    </div>
                    <div className="flex items-center gap-2">
                      <VerificationBadge
                        status={t.verification_status}
                        label={titleCase(t.verification_status)}
                      />
                      <Button size="sm" variant="outline" onClick={() => setReviewing(t)}>
                        {t.verification_status === "pending" ? "Review" : "Change"}
                        <span className="sr-only"> {t.full_name}</span>
                      </Button>
                    </div>
                  </li>
                ))}
              </ul>
            </SectionCard>
          )
        }
      </DataView>
      <FormDialog
        open={reviewing !== null}
        onClose={() => setReviewing(null)}
        title={reviewing ? `Review ${reviewing.full_name}` : "Review"}
        description="Check the registration with the issuing body before you decide."
      >
        {reviewing && (
          <ReviewForm
            therapist={reviewing}
            onCancel={() => setReviewing(null)}
            onDone={() => {
              setReviewing(null);
              void queue.reload();
            }}
          />
        )}
      </FormDialog>
    </>
  );
}
