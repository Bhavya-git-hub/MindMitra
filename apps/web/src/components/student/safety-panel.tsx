"use client";

import { HeartHandshake, LifeBuoy, Loader2 } from "lucide-react";
import Link from "next/link";
import * as React from "react";

import { InlineAlert } from "@/components/states/inline-alert";
import { ContactCard } from "@/components/student/emergency-view";
import { useSubmit } from "@/components/student/form-bits";
import { Button } from "@/components/ui/button";
import type { Safety, SupportRequest } from "@/lib/api/student-schemas";
import { useStudentApi } from "@/lib/hooks/use-student-api";
import { cn } from "@/lib/utils";

/** What the student is told about who knows. Never says what was written was shared. */
export function escalationText(safety: Safety): string | null {
  const { status, basis, care_team_notified } = safety.escalation;
  if (status === "requested") {
    return care_team_notified
      ? "Your counsellor has been asked to reach out to you. They won't see what you wrote."
      : "Your institution's counselling team has been asked to reach out to you. They won't see what you wrote.";
  }
  if (status === "already_open") {
    return "Your counsellor or the counselling team already knows and will reach out.";
  }
  if (status === "failed") {
    return "We couldn't reach the counselling team just now. Please contact one of the people below yourself.";
  }
  if (basis === "no_consent") {
    return "Nobody has been told about what you wrote. If you'd like a person to reach out, you can ask below.";
  }
  return null;
}

function AskForOutreach() {
  const api = useStudentApi();
  const [sent, setSent] = React.useState<SupportRequest | null>(null);
  const { pending, error, run } = useSubmit();
  if (sent) {
    return (
      <InlineAlert tone="success" title="Your request is in">
        {sent.already_open
          ? "You already have a request open, so we haven't sent another. Someone will be in touch."
          : "A person has been asked to reach out to you. If you feel you can't stay safe, call the emergency number instead of waiting."}
      </InlineAlert>
    );
  }
  return (
    <div className="space-y-2">
      <Button
        variant="outline"
        disabled={pending}
        onClick={() =>
          void run(async () => {
            setSent(await api.requestSupport());
          }, "We couldn't send your request. Please use one of the contacts above.")
        }
      >
        {pending ? (
          <Loader2 className="animate-spin" aria-hidden="true" />
        ) : (
          <HeartHandshake aria-hidden="true" />
        )}
        Ask someone to reach out
      </Button>
      {error && <InlineAlert tone="destructive">{error}</InlineAlert>}
    </div>
  );
}

/**
 * Immediate-support guidance, contacts and counsellor access, shown when what a student wrote
 * or reported suggests they may need support. Wording comes from the API (fixed and reviewed);
 * nothing here diagnoses, and it is not a replacement for emergency services.
 */
export function SafetyPanel({ safety }: { safety: Safety }) {
  const serious = safety.level !== "moderate";
  const told = escalationText(safety);
  return (
    <section
      role={serious ? "alert" : "status"}
      aria-labelledby="safety-panel-title"
      className={cn(
        "space-y-4 rounded-xl border p-5",
        serious ? "border-destructive/40 bg-destructive/5" : "border-info/30 bg-info-soft",
      )}
    >
      <h2 id="safety-panel-title" className="flex items-center gap-2 font-semibold">
        <LifeBuoy className="size-5 shrink-0" aria-hidden="true" />
        {safety.guidance.title}
      </h2>
      {safety.emergency_first && (
        <InlineAlert tone="warning" title="If you're in danger right now">
          Call your local emergency number now, or go to the nearest emergency department.
        </InlineAlert>
      )}
      <p className="max-w-prose">{safety.guidance.message}</p>
      <ol className="max-w-prose list-decimal space-y-1 pl-5">
        {safety.guidance.steps.map((step) => (
          <li key={step}>{step}</li>
        ))}
      </ol>
      {told && <p className="max-w-prose font-medium">{told}</p>}
      <ul aria-label="Support contacts" className="grid gap-3 sm:grid-cols-2">
        {safety.resources.map((r) => (
          <ContactCard key={r.id ?? r.label} c={r} />
        ))}
      </ul>
      <div className="flex flex-wrap gap-2">
        {safety.counselling.message_path && (
          <Button asChild variant={serious ? "default" : "outline"}>
            <Link href={safety.counselling.message_path}>Message your counsellor</Link>
          </Button>
        )}
        <Button asChild variant="outline">
          <Link href={safety.counselling.booking_path}>Book a counsellor</Link>
        </Button>
        <Button asChild variant="outline">
          <Link href="/student/emergency">Get help now</Link>
        </Button>
      </div>
      {safety.offer_outreach && <AskForOutreach />}
      {safety.recommendations_paused && (
        <p className="max-w-prose text-sm text-muted-foreground">
          We&apos;ve paused your usual suggestions for now, so support comes first.
        </p>
      )}
      <p role="note" className="max-w-prose text-sm text-muted-foreground">
        {safety.disclaimer}
      </p>
    </section>
  );
}
