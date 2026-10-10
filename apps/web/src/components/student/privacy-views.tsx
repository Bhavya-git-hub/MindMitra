"use client";

import { Download, Eye, ShieldCheck } from "lucide-react";
import Link from "next/link";
import * as React from "react";

import { SectionCard } from "@/components/cards/section-card";
import { PageHeader } from "@/components/layout/page-header";
import { InlineAlert } from "@/components/states/inline-alert";
import { DataView } from "@/components/student/data-view";
import { useSubmit } from "@/components/student/form-bits";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import type { Consent } from "@/lib/api/student-schemas";
import { formatDateTime, titleCase } from "@/lib/format";
import { useQuery } from "@/lib/hooks/use-query";
import { useStudentApi } from "@/lib/hooks/use-student-api";
import { notify } from "@/lib/toast";

const ROLE_LABELS: Record<string, string> = {
  therapist: "A therapist on your care team",
  teacher: "A teacher",
  administrator: "An administrator",
  student: "You",
  system: "MindMitra's systems",
};

function actorLabel(role: string | null): string {
  return role ? (ROLE_LABELS[role] ?? titleCase(role)) : "MindMitra's systems";
}

/** Saves the export as a file in the browser; nothing is kept anywhere else. */
function saveJson(data: unknown, filename: string) {
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

// ---- privacy center -----------------------------------------------------------------------------

export function PrivacyCenterView() {
  const api = useStudentApi();
  const history = useQuery("access-history", () => api.accessHistory());
  const { pending, error, run } = useSubmit();

  function download() {
    void run(async () => {
      const data = await api.exportData();
      saveJson(data, `mindmitra-my-data-${new Date().toISOString().slice(0, 10)}.json`);
      notify.success("Your data has been downloaded");
    }, "We couldn't prepare your download. Please try again.");
  }

  return (
    <>
      <PageHeader
        title="Privacy"
        description="You decide who sees what. Here's how your information is handled."
        actions={
          <Button asChild>
            <Link href="/student/privacy/consent">
              <ShieldCheck aria-hidden="true" />
              Manage consent
            </Link>
          </Button>
        }
      />
      <SectionCard title="How your information is handled">
        <ul className="max-w-prose list-disc space-y-2 pl-5">
          <li>
            Your private notes and journal are visible only to you. Nobody else can read them.
          </li>
          <li>
            A therapist can see your mood check-ins only if they&apos;re on your care team{" "}
            <strong>and</strong> you&apos;ve allowed it. Turning it off takes effect straight away.
          </li>
          <li>
            Therapists&apos; own session notes belong to them. Teachers and administrators never see
            your individual wellbeing data.
          </li>
          <li>
            Combined statistics never show groups smaller than 10 people, so no one can be picked
            out.
          </li>
        </ul>
      </SectionCard>

      <SectionCard
        title="Download my data"
        description="Everything you have added to MindMitra, as one file you can keep."
      >
        <div className="space-y-3">
          {error && <InlineAlert tone="destructive">{error}</InlineAlert>}
          <Button onClick={download} disabled={pending}>
            <Download aria-hidden="true" />
            {pending ? "Preparing…" : "Download my data"}
          </Button>
          <p className="text-sm text-muted-foreground">
            The file contains personal information, so keep it somewhere safe. It doesn&apos;t
            include notes your therapist has written.
          </p>
        </div>
      </SectionCard>

      <SectionCard
        title="Who has looked at my data"
        description="Times when someone else viewed your information. We show the role, not the person."
      >
        <DataView
          query={history}
          skeleton={<p className="text-sm text-muted-foreground">Loading…</p>}
        >
          {(events) =>
            events.length === 0 ? (
              <p className="flex items-center gap-2 text-sm text-muted-foreground">
                <Eye className="size-4" aria-hidden="true" />
                No one else has viewed your information.
              </p>
            ) : (
              <ul className="divide-y">
                {events.map((e, i) => (
                  <li
                    key={`${e.occurred_at}-${i}`}
                    className="flex flex-wrap justify-between gap-2 py-3"
                  >
                    <span>
                      {actorLabel(e.actor_role)} ·{" "}
                      <span className="text-muted-foreground">
                        {titleCase(e.action.replace(/[._]/g, " ").toLowerCase())}
                      </span>
                    </span>
                    <span className="text-sm text-muted-foreground">
                      {formatDateTime(e.occurred_at)}
                    </span>
                  </li>
                ))}
              </ul>
            )
          }
        </DataView>
      </SectionCard>
    </>
  );
}

// ---- consent management -------------------------------------------------------------------------

function ConsentRow({ consent, onChanged }: { consent: Consent; onChanged: () => Promise<void> }) {
  const api = useStudentApi();
  const { pending, error, run } = useSubmit();
  const titleId = React.useId();
  const descId = React.useId();

  function toggle(next: boolean) {
    void run(async () => {
      await api.setConsent(consent.scope, next);
      notify.success(next ? "Sharing turned on" : "Sharing turned off");
      await onChanged();
    }, "We couldn't update that setting. Please try again.");
  }

  return (
    <li className="space-y-2 py-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="max-w-prose space-y-1">
          <h3 id={titleId} className="font-medium">
            {consent.title}
          </h3>
          <p id={descId} className="text-sm text-muted-foreground">
            {consent.description}
          </p>
          {consent.granted && consent.granted_at && (
            <p className="text-sm text-muted-foreground">
              On since {formatDateTime(consent.granted_at)}
            </p>
          )}
        </div>
        {consent.required ? (
          <Badge variant="success">Required</Badge>
        ) : (
          <button
            type="button"
            role="switch"
            aria-checked={consent.granted}
            aria-labelledby={titleId}
            aria-describedby={descId}
            disabled={pending}
            onClick={() => toggle(!consent.granted)}
            className="inline-flex min-h-10 shrink-0 items-center gap-2 rounded-full border bg-card px-4 text-sm focus-visible:ring-[3px] focus-visible:ring-ring/50 focus-visible:outline-none disabled:opacity-50"
          >
            <span
              aria-hidden="true"
              className={
                consent.granted
                  ? "size-3 rounded-full bg-primary"
                  : "size-3 rounded-full border border-muted-foreground"
              }
            />
            {consent.granted ? "On" : "Off"}
          </button>
        )}
      </div>
      {error && <InlineAlert tone="destructive">{error}</InlineAlert>}
    </li>
  );
}

export function ConsentView() {
  const api = useStudentApi();
  const consents = useQuery("consents", () => api.consents());
  return (
    <>
      <PageHeader
        title="Consent"
        description="Choose what is shared and what isn't. You can change any of these at any time."
        actions={
          <Button asChild variant="ghost">
            <Link href="/student/privacy">Privacy</Link>
          </Button>
        }
      />
      <DataView query={consents}>
        {(rows) => (
          <SectionCard title="Your choices">
            <ul className="divide-y">
              {rows.map((c) => (
                <ConsentRow key={c.scope} consent={c} onChanged={consents.reload} />
              ))}
            </ul>
          </SectionCard>
        )}
      </DataView>
    </>
  );
}
