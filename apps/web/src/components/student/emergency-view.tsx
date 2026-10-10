"use client";

import { ExternalLink, HeartHandshake, Phone } from "lucide-react";
import Link from "next/link";
import * as React from "react";

import { SectionCard } from "@/components/cards/section-card";
import { PageHeader } from "@/components/layout/page-header";
import { EmptyState } from "@/components/states/empty-state";
import { InlineAlert } from "@/components/states/inline-alert";
import { DataView } from "@/components/student/data-view";
import { SaveButton, useSubmit } from "@/components/student/form-bits";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import type { CrisisContact, SupportRequest } from "@/lib/api/student-schemas";
import { useQuery } from "@/lib/hooks/use-query";
import { useStudentApi } from "@/lib/hooks/use-student-api";

const GROUPS: { kind: string; title: string }[] = [
  { kind: "emergency", title: "In an emergency" },
  { kind: "helpline", title: "Helplines you can call or text" },
  { kind: "campus", title: "At your institution" },
];

/** Digits and a leading + only, so the number can be dialled from a phone. */
export function dialable(phone: string): string {
  return phone.replace(/[^\d+]/g, "");
}

function ContactCard({ c }: { c: CrisisContact }) {
  return (
    <li className="space-y-2 rounded-xl border bg-card p-4">
      <h3 className="font-medium">{c.label}</h3>
      {c.description && <p className="text-sm text-muted-foreground">{c.description}</p>}
      {c.hours && <p className="text-sm text-muted-foreground">{c.hours}</p>}
      <div className="flex flex-wrap gap-2">
        {c.phone && (
          <Button asChild size="sm">
            <a href={`tel:${dialable(c.phone)}`}>
              <Phone aria-hidden="true" />
              Call {c.phone}
            </a>
          </Button>
        )}
        {c.url && /^https?:\/\//i.test(c.url) && (
          <Button asChild size="sm" variant="outline">
            <a href={c.url} target="_blank" rel="noopener noreferrer">
              Website
              <ExternalLink aria-hidden="true" />
              <span className="sr-only">(opens in a new tab)</span>
            </a>
          </Button>
        )}
      </div>
    </li>
  );
}

function ReachOutForm() {
  const api = useStudentApi();
  const [message, setMessage] = React.useState("");
  const [sent, setSent] = React.useState<SupportRequest | null>(null);
  const { pending, error, run } = useSubmit();

  if (sent) {
    return (
      <div role="status" className="space-y-2">
        <InlineAlert tone="success" title="Your request is in">
          {sent.already_open
            ? "You already have a request open, so we haven't sent another. Someone will be in touch."
            : sent.reaches_care_team
              ? "Your care team has been told, and a person will reach out."
              : "A member of your institution's support team has been asked to reach out."}
        </InlineAlert>
        <p className="text-sm text-muted-foreground">
          Replies can take a little while. If you feel you can&apos;t stay safe, please call the
          emergency number above instead of waiting.
        </p>
      </div>
    );
  }

  return (
    <form
      noValidate
      className="space-y-4"
      onSubmit={(e) => {
        e.preventDefault();
        void run(async () => {
          setSent(await api.requestSupport(message.trim() || undefined));
        }, "We couldn't send your request. Please use one of the numbers above.");
      }}
    >
      <p className="max-w-prose">
        If you&apos;d rather a person contacted you, you can ask here. A real person reads this, not
        a computer. This is not an emergency line.
      </p>
      <div className="space-y-2">
        <Label htmlFor="reach-out-message">Anything you&apos;d like them to know? (optional)</Label>
        <Textarea
          id="reach-out-message"
          value={message}
          onChange={(e) => setMessage(e.target.value)}
          maxLength={1000}
          rows={3}
        />
      </div>
      {error && <InlineAlert tone="destructive">{error}</InlineAlert>}
      <SaveButton pending={pending}>
        <HeartHandshake aria-hidden="true" />
        Ask someone to reach out
      </SaveButton>
    </form>
  );
}

export function EmergencyView() {
  const api = useStudentApi();
  const contacts = useQuery("crisis-contacts", () => api.crisisContacts());

  return (
    <>
      <PageHeader
        title="Urgent support"
        description="You don't have to handle this alone. Reaching out is a strong thing to do."
      />
      <InlineAlert tone="warning" title="If you or someone else is in immediate danger">
        Call your local emergency number now, or go to the nearest emergency department. If you can,
        tell someone near you.
      </InlineAlert>
      <DataView query={contacts}>
        {(rows) =>
          rows.length === 0 ? (
            <EmptyState
              icon={Phone}
              title="No contacts listed yet"
              description="Ask your department office or student services for the counselling centre."
              action={
                <Button asChild variant="outline">
                  <Link href="/help">More ways to get help</Link>
                </Button>
              }
            />
          ) : (
            <>
              {GROUPS.map(({ kind, title }) => {
                const group = rows.filter((c) => c.kind === kind);
                return group.length === 0 ? null : (
                  <SectionCard key={kind} title={title}>
                    <ul className="grid gap-3 sm:grid-cols-2">
                      {group.map((c) => (
                        <ContactCard key={c.id} c={c} />
                      ))}
                    </ul>
                  </SectionCard>
                );
              })}
              <p className="text-sm text-muted-foreground">
                <Badge variant="outline" className="mr-2">
                  Check before relying on these
                </Badge>
                Contact details are provided by your institution and can change. If a number
                doesn&apos;t connect, try another or call your local emergency number.
              </p>
            </>
          )
        }
      </DataView>
      <SectionCard title="Ask someone to reach out">
        <ReachOutForm />
      </SectionCard>
    </>
  );
}
