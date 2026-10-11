"use client";

import { MessageCircle, Send } from "lucide-react";
import Link from "next/link";
import * as React from "react";

import { SectionCard } from "@/components/cards/section-card";
import { PageHeader } from "@/components/layout/page-header";
import { EmptyState } from "@/components/states/empty-state";
import { InlineAlert } from "@/components/states/inline-alert";
import { DataView } from "@/components/student/data-view";
import { SaveButton, useSubmit } from "@/components/student/form-bits";
import { SafetyPanel } from "@/components/student/safety-panel";
import { SupportCallout } from "@/components/student/support-callout";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import type { Safety, SupportInfo } from "@/lib/api/student-schemas";
import { formatDateTime } from "@/lib/format";
import { useQuery } from "@/lib/hooks/use-query";
import { useStudentApi } from "@/lib/hooks/use-student-api";
import { useRealtimeEvent } from "@/lib/realtime/realtime-provider";
import { cn } from "@/lib/utils";

export type MessagingPortal = "student" | "therapist";

const MAX_LENGTH = 4000;
/** A safety net only: new messages normally arrive over the real-time connection. */
const REFRESH_MS = 120_000;

export function MessagesView({ portal = "student" }: { portal?: MessagingPortal } = {}) {
  const isTherapist = portal === "therapist";
  const base = `/${portal}/messages`;
  const api = useStudentApi();
  const conversations = useQuery("conversations", () => api.conversations());
  const reloadConversations = conversations.reload;

  useRealtimeEvent((event) => {
    if (event.type === "message" || event.type === "message_read" || event.type === "resync")
      void reloadConversations();
  });

  return (
    <>
      <PageHeader
        title="Messages"
        description={
          isTherapist
            ? "Private messages with the students you support. Messaging is not a crisis service: if a student may be in danger, follow your institution's urgent-care process."
            : "Private messages with the therapists on your care team. For anything urgent, please don't wait for a reply."
        }
        actions={
          isTherapist ? undefined : (
            <Button asChild variant="outline">
              <Link href="/student/emergency">Urgent support</Link>
            </Button>
          )
        }
      />
      <DataView query={conversations}>
        {(rows) =>
          rows.length === 0 ? (
            <EmptyState
              icon={MessageCircle}
              title="No conversations yet"
              description={
                isTherapist
                  ? "A conversation opens once you confirm a student's first appointment."
                  : "Messaging opens once a therapist has confirmed your first appointment."
              }
              action={
                isTherapist ? (
                  <Button asChild>
                    <Link href="/therapist/appointments">View appointment requests</Link>
                  </Button>
                ) : (
                  <Button asChild>
                    <Link href="/student/therapists">Find a therapist</Link>
                  </Button>
                )
              }
            />
          ) : (
            <SectionCard title="Conversations">
              <ul className="divide-y">
                {rows.map((c) => (
                  <li key={c.other_id}>
                    <Link
                      href={`${base}/${c.other_id}`}
                      className="flex flex-wrap items-center justify-between gap-2 rounded-lg py-4 hover:bg-accent/50 focus-visible:ring-[3px] focus-visible:ring-ring/50 focus-visible:outline-none"
                    >
                      <span className="min-w-0 space-y-1">
                        <span className="block font-medium">{c.other_name}</span>
                        <span className="block max-w-prose truncate text-sm text-muted-foreground">
                          {c.last_message_preview ?? "No messages yet"}
                        </span>
                      </span>
                      <span className="flex items-center gap-2 text-sm text-muted-foreground">
                        {c.unread_count > 0 && <Badge variant="info">{c.unread_count} new</Badge>}
                        {c.last_message_at && formatDateTime(c.last_message_at)}
                      </span>
                    </Link>
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

export function ConversationView({
  otherId,
  portal = "student",
}: {
  otherId: string;
  portal?: MessagingPortal;
}) {
  const isTherapist = portal === "therapist";
  const api = useStudentApi();
  const conversations = useQuery("conversations", () => api.conversations());
  const thread = useQuery(`messages-${otherId}`, () => api.messages(otherId));
  const [text, setText] = React.useState("");
  const [support, setSupport] = React.useState<SupportInfo | null>(null);
  const [safety, setSafety] = React.useState<Safety | null>(null);
  // One id per message the student writes, so a retry after a dropped connection can't duplicate it.
  const clientId = React.useRef<string | null>(null);
  const { pending, error, run } = useSubmit();
  const { reload } = thread;
  const reloadConversations = conversations.reload;

  const unread = thread.state.data?.some((m) => !m.mine && m.read_at === null) ?? false;
  React.useEffect(() => {
    if (!unread) return;
    void api
      .markConversationRead(otherId)
      .then(() => reloadConversations())
      .catch(() => undefined);
  }, [unread, api, otherId, reloadConversations]);

  React.useEffect(() => {
    const timer = window.setInterval(() => void reload(), REFRESH_MS);
    return () => window.clearInterval(timer);
  }, [reload]);

  // Only events about this conversation reload it; the ids say nothing about the content.
  useRealtimeEvent((event) => {
    if (event.type === "resync") {
      void reload();
      void reloadConversations();
    } else if (
      (event.type === "message" || event.type === "message_read") &&
      event.with === otherId
    ) {
      void reload();
      if (event.type === "message") void reloadConversations();
    }
  });

  const other = conversations.state.data?.find((c) => c.other_id === otherId);

  function submit(event: React.FormEvent) {
    event.preventDefault();
    const body = text.trim();
    if (!body) return;
    clientId.current ??= crypto.randomUUID();
    const id = clientId.current;
    void run(async () => {
      const sent = await api.sendMessage(otherId, body, id);
      clientId.current = null;
      setText("");
      setSupport(sent.support);
      setSafety(sent.safety ?? null);
      await Promise.all([reload(), reloadConversations()]);
    }, "Your message wasn't sent. Please try again.");
  }

  return (
    <>
      <PageHeader
        title={other?.other_name ?? "Conversation"}
        actions={
          <Button asChild variant="ghost">
            <Link href={`/${portal}/messages`}>All messages</Link>
          </Button>
        }
      />
      {!isTherapist &&
        (safety ? (
          <SafetyPanel safety={safety} />
        ) : (
          support && <SupportCallout message={support.message} />
        ))}
      <SectionCard
        title="Messages"
        description={
          isTherapist
            ? "Only you and this student can read these. Please don't put clinical notes here: keep those in your private session notes."
            : "Only you and this therapist can read these. Replies can take a while: for anything urgent, use urgent support."
        }
      >
        <DataView query={thread}>
          {(rows) => {
            // Oldest first, whatever order the API used.
            const chronological = [...rows].sort((x, y) =>
              x.created_at.localeCompare(y.created_at),
            );
            return chronological.length === 0 ? (
              <p className="text-sm text-muted-foreground">
                {isTherapist
                  ? "No messages yet."
                  : "No messages yet. Say hello whenever you\u2019re ready."}
              </p>
            ) : (
              <ol aria-label="Messages" aria-live="polite" className="space-y-3">
                {chronological.map((m) => (
                  <li key={m.id} className={cn("flex", m.mine ? "justify-end" : "justify-start")}>
                    <div
                      className={cn(
                        "max-w-[85%] space-y-1 rounded-2xl px-4 py-2.5",
                        m.mine ? "bg-primary text-primary-foreground" : "border bg-card",
                      )}
                    >
                      <p className="break-words whitespace-pre-wrap">{m.body}</p>
                      <p
                        className={cn(
                          "text-xs",
                          m.mine ? "text-primary-foreground/80" : "text-muted-foreground",
                        )}
                      >
                        <span className="sr-only">
                          {m.mine ? "You, " : `${other?.other_name}, `}
                        </span>
                        {formatDateTime(m.created_at)}
                        {m.mine && m.read_at ? " · Read" : ""}
                      </p>
                    </div>
                  </li>
                ))}
              </ol>
            );
          }}
        </DataView>
      </SectionCard>
      {other && !other.active ? (
        <InlineAlert tone="info">
          {isTherapist
            ? "This conversation has ended because the care link is no longer active, so you can read it but not reply."
            : "This conversation has ended, so you can read it but not reply. You can book a new appointment any time."}
        </InlineAlert>
      ) : (
        <form onSubmit={submit} className="space-y-3" noValidate>
          <Label htmlFor="message-body">Write a message</Label>
          <Textarea
            id="message-body"
            value={text}
            onChange={(e) => setText(e.target.value)}
            maxLength={MAX_LENGTH}
            rows={3}
          />
          {error && <InlineAlert tone="destructive">{error}</InlineAlert>}
          <SaveButton pending={pending} disabled={pending || text.trim() === ""}>
            <Send aria-hidden="true" />
            Send
          </SaveButton>
        </form>
      )}
    </>
  );
}
