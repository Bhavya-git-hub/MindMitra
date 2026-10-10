"use client";

import { Bot, ShieldCheck } from "lucide-react";
import Link from "next/link";

import { SectionCard } from "@/components/cards/section-card";
import { PageHeader } from "@/components/layout/page-header";
import { InlineAlert } from "@/components/states/inline-alert";
import { DataView } from "@/components/student/data-view";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { formatDateTime } from "@/lib/format";
import { useQuery } from "@/lib/hooks/use-query";
import { useStudentApi } from "@/lib/hooks/use-student-api";

/**
 * The entry point for the companion. The conversation itself is not built yet, so this page says
 * so plainly rather than pretending, and points to the things that do work.
 */
export function AssistantView() {
  const api = useStudentApi();
  const conversations = useQuery("ai-conversations", () => api.aiConversations());

  return (
    <>
      <PageHeader
        title="Companion"
        description="A space to talk things through, any time of day."
      />
      <InlineAlert tone="info" title="The companion isn't available yet">
        We&apos;re building it carefully, and we won&apos;t switch it on until it&apos;s ready. In
        the meantime you can check in, write notes to yourself, or talk to a real person.
      </InlineAlert>
      <SectionCard title="What to expect">
        <ul className="space-y-3">
          <li className="flex gap-3">
            <Bot className="mt-0.5 size-5 shrink-0 text-primary" aria-hidden="true" />
            <span>
              The companion is an AI. It can listen, help you reflect and suggest coping ideas. It
              is <strong>not a therapist</strong> and cannot diagnose anything.
            </span>
          </li>
          <li className="flex gap-3">
            <ShieldCheck className="mt-0.5 size-5 shrink-0 text-primary" aria-hidden="true" />
            <span>
              It will only use your data if you allow it, and you can change that at any time in
              your{" "}
              <Link href="/student/privacy/consent" className="underline underline-offset-4">
                consent settings
              </Link>
              .
            </span>
          </li>
        </ul>
        <div className="mt-4 flex flex-wrap gap-2">
          <Button asChild>
            <Link href="/student/check-in">Daily check-in</Link>
          </Button>
          <Button asChild variant="outline">
            <Link href="/student/therapists">Talk to a therapist</Link>
          </Button>
          <Button asChild variant="outline">
            <Link href="/student/emergency">Urgent support</Link>
          </Button>
        </div>
      </SectionCard>
      <DataView query={conversations} skeleton={null}>
        {(rows) =>
          rows.length === 0 ? null : (
            <SectionCard title="Earlier conversations">
              <ul className="divide-y">
                {rows.map((c) => (
                  <li key={c.id} className="flex flex-wrap justify-between gap-2 py-3">
                    <span>{formatDateTime(c.started_at)}</span>
                    <Badge variant="outline">{c.status}</Badge>
                  </li>
                ))}
              </ul>
            </SectionCard>
          )
        }
      </DataView>
    </>
  );
}
