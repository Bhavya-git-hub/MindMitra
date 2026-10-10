"use client";

import { HeartHandshake } from "lucide-react";
import * as React from "react";

import { SectionCard } from "@/components/cards/section-card";
import { PageHeader } from "@/components/layout/page-header";
import { EmptyState } from "@/components/states/empty-state";
import { InlineAlert } from "@/components/states/inline-alert";
import { DataView } from "@/components/student/data-view";
import { NativeSelect, SaveButton, useSubmit } from "@/components/student/form-bits";
import { REFERRAL_STATUS_VARIANT, StatusBadge, URGENCY_VARIANT } from "@/components/teacher/shared";
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
import { Label } from "@/components/ui/label";
import { REFERRAL_OUTCOMES, type TriageReferral } from "@/lib/api/teacher-schemas";
import { formatDateTime } from "@/lib/format";
import { useQuery } from "@/lib/hooks/use-query";
import { useTeacherApi } from "@/lib/hooks/use-teacher-api";
import { notify } from "@/lib/toast";

import { RequireVerified, SegmentedTabs } from "./shared";

function CloseDialog({
  referral,
  onClose,
  onClosed,
}: {
  referral: TriageReferral | null;
  onClose: () => void;
  onClosed: () => Promise<void>;
}) {
  const api = useTeacherApi();
  const [outcome, setOutcome] = React.useState("");
  const [formError, setFormError] = React.useState<string>();
  const { pending, error, run, clearError } = useSubmit();

  function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!referral) return;
    if (!outcome) {
      setFormError("Choose how this ended.");
      return;
    }
    setFormError(undefined);
    void run(async () => {
      await api.closeReferral(referral.id, outcome);
      notify.success("Referral closed");
      setOutcome("");
      onClose();
      await onClosed();
    }, "We couldn't close that referral.");
  }

  return (
    <Dialog
      open={referral !== null}
      onOpenChange={(open) => {
        if (!open) {
          clearError();
          setFormError(undefined);
          onClose();
        }
      }}
    >
      <DialogContent>
        <form onSubmit={submit} className="space-y-4" noValidate>
          <DialogHeader>
            <DialogTitle>Close this referral</DialogTitle>
            <DialogDescription>
              The teacher will only see that it is closed, not how.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-2">
            <Label htmlFor="ref-outcome">How did it end?</Label>
            <NativeSelect
              id="ref-outcome"
              value={outcome}
              onChange={(e) => setOutcome(e.target.value)}
              aria-invalid={formError ? true : undefined}
            >
              <option value="">Choose…</option>
              {REFERRAL_OUTCOMES.map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </NativeSelect>
            {formError && (
              <p role="alert" className="text-sm text-destructive">
                {formError}
              </p>
            )}
          </div>
          {error && <InlineAlert tone="destructive">{error}</InlineAlert>}
          <DialogFooter>
            <Button type="button" variant="ghost" onClick={onClose}>
              Not yet
            </Button>
            <SaveButton pending={pending}>Close referral</SaveButton>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function ReferralCard({
  r,
  onChanged,
  onClose,
}: {
  r: TriageReferral;
  onChanged: () => Promise<void>;
  onClose: (r: TriageReferral) => void;
}) {
  const api = useTeacherApi();
  const { pending, error, run } = useSubmit();
  return (
    <li className="space-y-3 rounded-xl border bg-card p-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="space-y-1">
          <h3 className="font-medium">
            {r.student_name} · {r.category_label}
          </h3>
          <p className="text-sm text-muted-foreground">
            From {r.teacher_name} ({r.course_code}) · {r.department_name} ·{" "}
            {formatDateTime(r.created_at)}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <StatusBadge status={r.urgency} label={r.urgency_label} variants={URGENCY_VARIANT} />
          <StatusBadge
            status={r.status}
            label={r.status === "received" ? "Waiting" : r.status_label}
            variants={REFERRAL_STATUS_VARIANT}
          />
          <Badge variant="outline">{r.on_my_team ? "Your student" : "Not on a care team"}</Badge>
        </div>
      </div>
      {r.note && (
        <blockquote className="border-l-2 pl-3 text-sm break-words text-muted-foreground">
          {r.note}
        </blockquote>
      )}
      {r.outcome_label && <p className="text-sm">Outcome: {r.outcome_label}</p>}
      {error && <InlineAlert tone="destructive">{error}</InlineAlert>}
      <div className="flex flex-wrap gap-2">
        {r.status === "received" && (
          <Button
            size="sm"
            disabled={pending}
            onClick={() =>
              void run(async () => {
                await api.claimReferral(r.id);
                notify.success("Picked up. The student has been told someone will check in.");
                await onChanged();
              }, "We couldn't pick that up.")
            }
          >
            Pick this up
          </Button>
        )}
        {r.status === "in_progress" && r.claimed_by_me && (
          <Button size="sm" variant="outline" disabled={pending} onClick={() => onClose(r)}>
            Close
          </Button>
        )}
      </div>
    </li>
  );
}

function Body() {
  const api = useTeacherApi();
  const [show, setShow] = React.useState<"open" | "closed">("open");
  const rows = useQuery(`t-referrals-${show}`, async () => {
    if (show === "closed") return api.triageQueue("closed");
    return api.triageQueue();
  });
  const [closing, setClosing] = React.useState<TriageReferral | null>(null);
  return (
    <>
      <SegmentedTabs
        label="Show"
        value={show}
        onChange={setShow}
        options={[
          { value: "open", label: "Open" },
          { value: "closed", label: "Closed" },
        ]}
      />
      <DataView query={rows}>
        {(list) =>
          list.length === 0 ? (
            <EmptyState
              icon={HeartHandshake}
              title={show === "open" ? "No open referrals" : "No closed referrals"}
              description={
                show === "open"
                  ? "Referrals from teachers about your students, or students with no care team, show here."
                  : undefined
              }
            />
          ) : (
            <SectionCard
              title={show === "open" ? "Waiting for a person" : "Closed"}
              description="Most urgent first."
            >
              <ul className="space-y-4">
                {list.map((r) => (
                  <ReferralCard key={r.id} r={r} onChanged={rows.reload} onClose={setClosing} />
                ))}
              </ul>
            </SectionCard>
          )
        }
      </DataView>
      <CloseDialog referral={closing} onClose={() => setClosing(null)} onClosed={rows.reload} />
    </>
  );
}

export function TriageReferralsView() {
  return (
    <>
      <PageHeader
        title="Referrals from teachers"
        description="A teacher has asked for someone to reach out. Please contact the student kindly and in your own words."
      />
      <RequireVerified>
        <Body />
      </RequireVerified>
    </>
  );
}
