"use client";

import { Bot, LifeBuoy, MessageCircleHeart, Send, ShieldCheck, Trash2 } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import * as React from "react";

import { SectionCard } from "@/components/cards/section-card";
import { PageHeader } from "@/components/layout/page-header";
import { useModal } from "@/components/providers/modal-provider";
import { InlineAlert } from "@/components/states/inline-alert";
import { DataView } from "@/components/student/data-view";
import { ContactCard } from "@/components/student/emergency-view";
import { SaveButton } from "@/components/student/form-bits";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import type {
  CompanionConversation,
  CompanionMessage,
  CompanionStatus,
  CompanionSupport,
} from "@/lib/api/companion-schemas";
import { describeError, isApiError } from "@/lib/api/errors";
import type { CrisisContact } from "@/lib/api/student-schemas";
import { formatDateTime, formatShortDate } from "@/lib/format";
import { useCompanionApi } from "@/lib/hooks/use-companion-api";
import { useQuery } from "@/lib/hooks/use-query";
import { useStudentApi } from "@/lib/hooks/use-student-api";
import { notify } from "@/lib/toast";
import { cn } from "@/lib/utils";

/** The API refuses longer messages too; this keeps the limit visible while typing. */
export const MAX_MESSAGE = 2000;

/** Shown until the API's own wording has loaded. Kept in step with the API's disclaimer. */
const DEFAULT_DISCLAIMER =
  "I'm an AI wellness companion, not a therapist. I can't diagnose or give medical advice, and I can make mistakes. If you're in danger, use Get help now.";

const STATUS_LABEL: Record<string, string> = {
  active: "Open",
  crisis_handoff: "Support offered",
  ended: "Ended",
};

function offMessage(status: CompanionStatus): string {
  return status.reason === "switched_off"
    ? "Your institution has switched the companion off for now."
    : "The companion isn't available right now. Please try again later.";
}

function retentionNote(status: CompanionStatus): string {
  return status.keeps_history
    ? "You've chosen to keep conversations, so each one is deleted 90 days after your last message."
    : "Conversations are deleted a day after your last message. You can choose to keep them for 90 days in your consent settings.";
}

/** What the companion is and is not. Shown before the first conversation and on every chat. */
function Disclaimer({ text }: { text: string }) {
  return (
    <p
      role="note"
      className="flex items-start gap-3 rounded-xl border bg-muted/40 p-4 text-sm text-muted-foreground"
    >
      <Bot className="mt-0.5 size-5 shrink-0 text-primary" aria-hidden="true" />
      <span>{text}</span>
    </p>
  );
}

/** Ways to reach a person. `crisis` means someone has been alerted; `gentle` only offers help. */
function SupportPanel({
  level,
  support,
}: {
  level: "crisis" | "gentle";
  support: CompanionSupport | null;
}) {
  const crisis = level === "crisis";
  return (
    <section
      role={crisis ? "alert" : "status"}
      aria-labelledby="companion-support-title"
      className={cn(
        "space-y-4 rounded-xl border p-5",
        crisis ? "border-destructive/40 bg-destructive/5" : "border-info/30 bg-info-soft",
      )}
    >
      <h2 id="companion-support-title" className="flex items-center gap-2 font-semibold">
        <LifeBuoy className="size-5 shrink-0" aria-hidden="true" />
        {crisis ? "Please talk to a person now" : "Support is here if you need it"}
      </h2>
      <p className="max-w-prose">
        {crisis
          ? "If you or anyone else is in immediate danger, call your local emergency number now."
          : "If things feel like too much, talking to a person can help. These contacts are there for you."}
      </p>
      {support?.about_someone_else && (
        <p className="max-w-prose">
          If someone else may be in danger, contact emergency services or campus support for them
          now.
        </p>
      )}
      {support ? <ContactList contacts={support.contacts} /> : <SavedContacts />}
      <Button asChild variant={crisis ? "default" : "outline"}>
        <Link href="/student/emergency">Get help now</Link>
      </Button>
    </section>
  );
}

function ContactList({ contacts }: { contacts: CrisisContact[] }) {
  if (contacts.length === 0) return null;
  return (
    <ul aria-label="Support contacts" className="grid gap-3 sm:grid-cols-2">
      {contacts.map((c) => (
        <ContactCard key={c.id} c={c} />
      ))}
    </ul>
  );
}

/** Contacts for a reopened conversation, where the reply that offered them was earlier. */
function SavedContacts() {
  const api = useStudentApi();
  const contacts = useQuery("crisis-contacts", () => api.crisisContacts());
  return (
    <DataView query={contacts} skeleton={null}>
      {(rows) => <ContactList contacts={rows} />}
    </DataView>
  );
}

export function CompanionHomeView() {
  const api = useCompanionApi();
  const router = useRouter();
  const status = useQuery("companion-status", () => api.status());
  const conversations = useQuery("companion-conversations", () => api.conversations());
  const [starting, setStarting] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  async function start() {
    setStarting(true);
    setError(null);
    try {
      const conversation = await api.start();
      router.push(`/student/assistant/${conversation.id}`);
    } catch (e) {
      setError(describeError(e, "We couldn't start a conversation. Please try again."));
      setStarting(false);
    }
  }

  return (
    <>
      <PageHeader
        title="Companion"
        description="A space to talk things through, any time of day."
        actions={
          <Button asChild variant="outline">
            <Link href="/student/emergency">Get help now</Link>
          </Button>
        }
      />
      <DataView query={status}>
        {(s) =>
          s.available ? (
            <SectionCard title="Before you start">
              <div className="space-y-4">
                <Disclaimer text={s.disclaimer} />
                <ul className="space-y-3">
                  <li className="flex gap-3">
                    <MessageCircleHeart
                      className="mt-0.5 size-5 shrink-0 text-primary"
                      aria-hidden="true"
                    />
                    <span>
                      It can help with things like exam stress, feeling homesick or lonely,
                      comparing yourself to others, sleep, money worries and settling in.
                    </span>
                  </li>
                  <li className="flex gap-3">
                    <LifeBuoy className="mt-0.5 size-5 shrink-0 text-primary" aria-hidden="true" />
                    <span>
                      If you might not be safe, it won&apos;t try to handle that itself. It shows
                      you people to contact and asks your institution&apos;s counselling team to
                      reach out.
                    </span>
                  </li>
                  <li className="flex gap-3">
                    <ShieldCheck
                      className="mt-0.5 size-5 shrink-0 text-primary"
                      aria-hidden="true"
                    />
                    <span>
                      {retentionNote(s)} You can delete a conversation at any time. Change this in
                      your{" "}
                      <Link
                        href="/student/privacy/consent"
                        className="underline underline-offset-4"
                      >
                        consent settings
                      </Link>
                      .
                    </span>
                  </li>
                </ul>
                {error && <InlineAlert tone="destructive">{error}</InlineAlert>}
                <div className="flex flex-wrap items-center gap-3">
                  <Button onClick={() => void start()} disabled={starting}>
                    Start a conversation
                  </Button>
                  <span className="text-sm text-muted-foreground">
                    {s.remaining_today} of {s.daily_limit} messages left today
                  </span>
                </div>
              </div>
            </SectionCard>
          ) : (
            <InlineAlert tone="info" title="The companion is off">
              {offMessage(s)} You can still check in, write notes to yourself, or{" "}
              <Link href="/student/therapists" className="underline underline-offset-4">
                talk to a therapist
              </Link>
              .
            </InlineAlert>
          )
        }
      </DataView>
      <DataView query={conversations} skeleton={null}>
        {(rows) =>
          rows.length === 0 ? null : (
            <SectionCard title="Your conversations">
              <ul className="divide-y">
                {rows.map((c) => (
                  <ConversationRow key={c.id} c={c} />
                ))}
              </ul>
            </SectionCard>
          )
        }
      </DataView>
    </>
  );
}

function ConversationRow({ c }: { c: CompanionConversation }) {
  return (
    <li>
      <Link
        href={`/student/assistant/${c.id}`}
        className="flex flex-wrap items-center justify-between gap-2 rounded-lg py-4 hover:bg-accent/50 focus-visible:ring-[3px] focus-visible:ring-ring/50 focus-visible:outline-none"
      >
        <span className="space-y-1">
          <span className="block font-medium">
            Conversation from {formatDateTime(c.started_at)}
          </span>
          {c.expires_at && (
            <span className="block text-sm text-muted-foreground">
              Deleted on {formatShortDate(c.expires_at)}
            </span>
          )}
        </span>
        <Badge variant={c.status === "crisis_handoff" ? "warning" : "outline"}>
          {STATUS_LABEL[c.status] ?? c.status}
        </Badge>
      </Link>
    </li>
  );
}

/** Friendly words for a failed send. The API's own detail is written for students. */
function sendError(e: unknown): string {
  if (isApiError(e) && [409, 429, 503].includes(e.status) && e.detail) {
    return e.status === 429 && e.retryAfterSeconds && e.retryAfterSeconds > 60
      ? `${e.detail} If you need to talk to someone now, use Get help now.`
      : e.detail;
  }
  return describeError(e, "Your message wasn't sent. Please try again.");
}

export function CompanionChatView({ conversationId }: { conversationId: string }) {
  const api = useCompanionApi();
  const router = useRouter();
  const modal = useModal();
  const status = useQuery("companion-status", () => api.status());
  const detail = useQuery(`companion-${conversationId}`, () => api.conversation(conversationId));
  const [text, setText] = React.useState("");
  const [sending, setSending] = React.useState<string | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [support, setSupport] = React.useState<CompanionSupport | null>(null);
  const { reload } = detail;

  const s = status.state.data;
  const available = s?.available ?? true;
  const messages = detail.state.data?.messages ?? [];
  const lastReply = [...messages].reverse().find((m) => m.role === "assistant");
  const supportLevel: "crisis" | "gentle" | null = support
    ? support.level
    : lastReply?.show_support
      ? lastReply.kind === "crisis"
        ? "crisis"
        : "gentle"
      : null;

  async function send() {
    const body = text.trim();
    if (!body || sending !== null) return;
    setSending(body);
    setError(null);
    try {
      const exchange = await api.send(conversationId, body);
      setText("");
      setSupport(exchange.support);
      await Promise.all([reload(), status.reload()]);
    } catch (e) {
      setError(sendError(e));
    } finally {
      setSending(null);
    }
  }

  async function remove() {
    const ok = await modal.confirm({
      title: "Delete this conversation?",
      description: "It will be deleted straight away and can't be recovered.",
      confirmLabel: "Delete",
      destructive: true,
    });
    if (!ok) return;
    try {
      await api.remove(conversationId);
      notify.success("Conversation deleted");
      router.push("/student/assistant");
    } catch (e) {
      notify.error("That didn't work", describeError(e));
    }
  }

  return (
    <>
      <PageHeader
        title="Companion"
        actions={
          <>
            <Button asChild variant="ghost">
              <Link href="/student/assistant">All conversations</Link>
            </Button>
            <Button variant="outline" onClick={() => void remove()}>
              <Trash2 aria-hidden="true" />
              Delete
            </Button>
          </>
        }
      />
      <Disclaimer text={s?.disclaimer ?? DEFAULT_DISCLAIMER} />
      <SectionCard title="Conversation">
        <DataView query={detail}>
          {(d) => <MessageList messages={d.messages} sending={sending} />}
        </DataView>
      </SectionCard>
      {supportLevel && <SupportPanel level={supportLevel} support={support} />}
      {available ? (
        <form
          noValidate
          className="space-y-3"
          onSubmit={(e) => {
            e.preventDefault();
            void send();
          }}
        >
          <Label htmlFor="companion-message">Your message</Label>
          <Textarea
            id="companion-message"
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
                e.preventDefault();
                void send();
              }
            }}
            maxLength={MAX_MESSAGE}
            rows={3}
            aria-describedby="companion-message-hint"
          />
          <p id="companion-message-hint" className="text-sm text-muted-foreground">
            {text.length} of {MAX_MESSAGE} characters. Press Ctrl+Enter to send. Please don&apos;t
            share names, phone numbers or addresses.
          </p>
          {error && <InlineAlert tone="destructive">{error}</InlineAlert>}
          <SaveButton pending={sending !== null} disabled={sending !== null || text.trim() === ""}>
            <Send aria-hidden="true" />
            Send
          </SaveButton>
        </form>
      ) : (
        s && (
          <InlineAlert tone="info" title="The companion is off">
            {offMessage(s)} You can still read this conversation.
          </InlineAlert>
        )
      )}
    </>
  );
}

function MessageList({
  messages,
  sending,
}: {
  messages: CompanionMessage[];
  sending: string | null;
}) {
  const ordered = [...messages].sort((a, b) => a.seq - b.seq);
  return (
    <div className="space-y-3">
      {ordered.length === 0 && sending === null && (
        <p className="text-sm text-muted-foreground">
          What&apos;s on your mind? You can start with something small.
        </p>
      )}
      <div role="log" aria-label="Messages" aria-live="polite">
        <ol className="space-y-3">
          {ordered.map((m) => (
            <Bubble key={m.id} mine={m.role === "user"} content={m.content} at={m.created_at} />
          ))}
          {sending !== null && <Bubble mine content={sending} at={null} />}
        </ol>
      </div>
      {sending !== null && (
        <p role="status" className="text-sm text-muted-foreground">
          The companion is replying…
        </p>
      )}
    </div>
  );
}

function Bubble({ mine, content, at }: { mine: boolean; content: string; at: string | null }) {
  return (
    <li className={cn("flex", mine ? "justify-end" : "justify-start")}>
      <div
        className={cn(
          "max-w-[85%] space-y-1 rounded-2xl px-4 py-2.5",
          mine ? "bg-primary text-primary-foreground" : "border bg-card",
        )}
      >
        <p className="break-words whitespace-pre-wrap">
          <span className="sr-only">{mine ? "You: " : "Companion (AI): "}</span>
          {content}
        </p>
        <p className={cn("text-xs", mine ? "text-primary-foreground/80" : "text-muted-foreground")}>
          {at ? formatDateTime(at) : "Sending…"}
        </p>
      </div>
    </li>
  );
}
