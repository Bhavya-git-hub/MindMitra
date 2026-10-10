"use client";

import { Bell } from "lucide-react";
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
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { ALERT_OUTCOMES, type RiskAlert } from "@/lib/api/therapist-schemas";
import { formatDateTime, titleCase } from "@/lib/format";
import { useQuery } from "@/lib/hooks/use-query";
import { useTherapistApi } from "@/lib/hooks/use-therapist-api";
import { notify } from "@/lib/toast";

import { RequireVerified, SEVERITY_LABELS, SEVERITY_VARIANT, SegmentedTabs } from "./shared";

function ResolveDialog({
  alert,
  onClose,
  onResolved,
}: {
  alert: RiskAlert | null;
  onClose: () => void;
  onResolved: () => Promise<void>;
}) {
  const api = useTherapistApi();
  const [outcome, setOutcome] = React.useState("");
  const [formError, setFormError] = React.useState<string>();
  const { pending, error, run, clearError } = useSubmit();

  function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!alert) return;
    if (!outcome) {
      setFormError("Choose how this was resolved.");
      return;
    }
    setFormError(undefined);
    void run(async () => {
      await api.actOnAlert(alert.id, "resolve", outcome);
      notify.success("Alert resolved");
      setOutcome("");
      onClose();
      await onResolved();
    }, "We couldn't resolve that alert.");
  }

  return (
    <Dialog
      open={alert !== null}
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
            <DialogTitle>Resolve this alert</DialogTitle>
            <DialogDescription>
              {alert ? `${alert.student_name}. ` : ""}Say what happened. This is recorded without
              any private details.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-2">
            <Label htmlFor="alert-outcome">What happened</Label>
            <NativeSelect
              id="alert-outcome"
              value={outcome}
              onChange={(e) => setOutcome(e.target.value)}
              aria-invalid={formError ? true : undefined}
            >
              <option value="">Choose…</option>
              {ALERT_OUTCOMES.map(([value, label]) => (
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
            <SaveButton pending={pending}>Resolve alert</SaveButton>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function AlertCard({
  a,
  onChanged,
  onResolve,
}: {
  a: RiskAlert;
  onChanged: () => Promise<void>;
  onResolve: (a: RiskAlert) => void;
}) {
  const api = useTherapistApi();
  const { pending, error, run } = useSubmit();

  function act(action: "acknowledge" | "start") {
    void run(async () => {
      await api.actOnAlert(a.id, action);
      await onChanged();
    }, "We couldn't update that alert.");
  }

  const closed = a.status === "resolved" || a.status === "dismissed";
  return (
    <li className="space-y-3 rounded-xl border bg-card p-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="space-y-1">
          <h3 className="font-medium">
            <Link
              href={`/therapist/students/${a.student_id}`}
              className="underline-offset-4 hover:underline"
            >
              {a.student_name}
            </Link>{" "}
            · {a.category_label}
          </h3>
          <p className="text-sm text-muted-foreground">
            {a.source_label} · {formatDateTime(a.created_at)}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Badge variant={SEVERITY_VARIANT[a.severity] ?? "outline"}>
            {SEVERITY_LABELS[a.severity] ?? titleCase(a.severity)}
          </Badge>
          {a.overdue && <Badge variant="warning">Reply overdue</Badge>}
          <Badge variant="outline">{titleCase(a.status)}</Badge>
        </div>
      </div>
      {a.excerpt && (
        <blockquote className="border-l-2 pl-3 text-sm break-words text-muted-foreground">
          {a.excerpt}
        </blockquote>
      )}
      {a.sla_ack_due_at && !closed && !a.acknowledged_at && (
        <p className="text-sm text-muted-foreground">
          Please acknowledge by {formatDateTime(a.sla_ack_due_at)}.
        </p>
      )}
      {closed && a.outcome && (
        <p className="text-sm">
          Outcome: {ALERT_OUTCOMES.find(([v]) => v === a.outcome)?.[1] ?? titleCase(a.outcome)}
        </p>
      )}
      {error && <InlineAlert tone="destructive">{error}</InlineAlert>}
      {!closed && (
        <div className="flex flex-wrap gap-2">
          {(a.status === "open" || a.status === "escalated") && (
            <Button size="sm" disabled={pending} onClick={() => act("acknowledge")}>
              Acknowledge
            </Button>
          )}
          {a.status === "acknowledged" && (
            <Button size="sm" disabled={pending} onClick={() => act("start")}>
              Start reaching out
            </Button>
          )}
          {(a.status === "acknowledged" || a.status === "in_progress") && (
            <Button size="sm" variant="outline" disabled={pending} onClick={() => onResolve(a)}>
              Resolve
            </Button>
          )}
          <Button asChild size="sm" variant="ghost">
            <Link href={`/therapist/messages/${a.student_id}`}>Message</Link>
          </Button>
        </div>
      )}
      <p className="text-xs text-muted-foreground">{a.disclaimer}</p>
    </li>
  );
}

function AlertsBody() {
  const api = useTherapistApi();
  const [show, setShow] = React.useState<"open" | "closed">("open");
  const rows = useQuery(`t-alerts-${show}`, () => api.alerts(show === "closed"));
  const [resolving, setResolving] = React.useState<RiskAlert | null>(null);

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
              icon={Bell}
              title={show === "open" ? "No open alerts" : "No closed alerts"}
              description={
                show === "open"
                  ? "When a student asks for help or a safety check needs a person, it shows here."
                  : undefined
              }
            />
          ) : (
            <SectionCard
              title={show === "open" ? "Needs a person" : "Closed"}
              description="Most urgent first."
            >
              <ul className="space-y-4">
                {list.map((a) => (
                  <AlertCard key={a.id} a={a} onChanged={rows.reload} onResolve={setResolving} />
                ))}
              </ul>
            </SectionCard>
          )
        }
      </DataView>
      <ResolveDialog
        alert={resolving}
        onClose={() => setResolving(null)}
        onResolved={rows.reload}
      />
    </>
  );
}

export function AlertsView() {
  return (
    <>
      <PageHeader
        title="Risk alerts"
        description="Moments when a student may want a person to reach out. An alert is a prompt for care, never a conclusion about someone."
      />
      <RequireVerified>
        <AlertsBody />
      </RequireVerified>
    </>
  );
}
