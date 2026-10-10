"use client";

import { Bell, BellOff } from "lucide-react";
import Link from "next/link";
import * as React from "react";

import { Button } from "@/components/ui/button";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from "@/components/ui/sheet";
import type { AppNotification } from "@/lib/api/notification-schemas";
import { createNotificationsApi } from "@/lib/api/notifications-api";
import { useAuth } from "@/lib/auth/auth-context";
import type { Role } from "@/lib/auth/roles";
import { formatDateTime } from "@/lib/format";
import { useQuery } from "@/lib/hooks/use-query";
import { useRealtimeEvent } from "@/lib/realtime/realtime-provider";
import { cn } from "@/lib/utils";

const PAGE = 20;

/** Where a notification leads, from its type and the reader's portal. Unknown ones lead nowhere. */
export function notificationHref(n: AppNotification, role: Role): string | null {
  switch (n.type) {
    case "new_message":
      return role === "student" || role === "therapist" ? `/${role}/messages` : null;
    case "appointment_update":
    case "appointment_reminder":
      return role === "student" || role === "therapist" ? `/${role}/appointments` : null;
    case "recommendation":
      return role === "student" ? "/student/recommendations" : null;
    case "risk_alert":
      return role === "therapist" ? "/therapist/alerts" : null;
    default:
      if (n.payload.request_id) {
        if (role === "teacher") return "/teacher/support-requests";
        if (role === "student") return "/student/teacher-support";
      }
      return null;
  }
}

function bellLabel(unread: number): string {
  if (unread === 0) return "Notifications";
  return `Notifications, ${unread > 99 ? "more than 99" : unread} unread`;
}

/**
 * The header bell: a count of unread notifications and a panel listing them. It updates as
 * notifications arrive over the real-time connection, and when the tab comes back into view.
 */
export function NotificationBell({ role }: { role: Role }) {
  const { manager } = useAuth();
  const api = React.useMemo(() => createNotificationsApi(manager.api), [manager]);
  const [open, setOpen] = React.useState(false);
  const count = useQuery("notifications-unread", () => api.unreadCount());
  const inbox = useQuery(`notifications-inbox-${open ? "open" : "closed"}`, () =>
    open ? api.inbox({ limit: PAGE }) : Promise.resolve(null),
  );
  const [busy, setBusy] = React.useState(false);
  const reloadCount = count.reload;
  const reloadInbox = inbox.reload;

  useRealtimeEvent((event) => {
    if (
      event.type === "notification" ||
      event.type === "notifications_read" ||
      event.type === "resync"
    ) {
      void reloadCount();
      if (open) void reloadInbox();
    }
  });

  const unread = count.state.data?.unread ?? 0;
  const items = inbox.state.data?.items ?? [];

  async function markAll() {
    setBusy(true);
    try {
      await api.markAllRead();
      await Promise.all([reloadCount(), reloadInbox()]);
    } catch {
      // The list stays as it was; the person can try again.
    } finally {
      setBusy(false);
    }
  }

  function openItem(n: AppNotification) {
    setOpen(false);
    if (n.read_at === null)
      void api.markRead(n.id).then(
        () => reloadCount(),
        () => undefined,
      );
  }

  return (
    <Sheet open={open} onOpenChange={setOpen}>
      <SheetTrigger asChild>
        <Button variant="ghost" size="icon" className="relative" aria-label={bellLabel(unread)}>
          <Bell className="size-5" aria-hidden="true" />
          {unread > 0 && (
            <span
              aria-hidden="true"
              className="absolute top-1 right-1 flex min-w-4 items-center justify-center rounded-full bg-primary px-1 text-[0.625rem] leading-4 font-semibold text-primary-foreground"
            >
              {unread > 9 ? "9+" : unread}
            </span>
          )}
        </Button>
      </SheetTrigger>
      <SheetContent
        side="right"
        closeLabel="Close notifications"
        className="w-full max-w-sm bg-background text-foreground sm:max-w-sm"
      >
        <SheetHeader className="pr-12">
          <SheetTitle>Notifications</SheetTitle>
          <SheetDescription>
            {unread === 0 ? "You're all caught up." : `${unread} unread.`} Notifications say
            something changed; open the app page to see what.
          </SheetDescription>
        </SheetHeader>
        <div className="flex items-center justify-end px-4">
          <Button
            size="sm"
            variant="outline"
            disabled={busy || unread === 0}
            onClick={() => void markAll()}
          >
            Mark all as read
          </Button>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto px-4 pb-6">
          {inbox.state.status === "loading" ? (
            <p className="text-sm text-muted-foreground">Loading…</p>
          ) : inbox.state.status === "error" ? (
            <p className="text-sm text-muted-foreground">
              We couldn&apos;t load your notifications. Please try again.
            </p>
          ) : items.length === 0 ? (
            <div className="flex flex-col items-center gap-2 py-10 text-center text-muted-foreground">
              <BellOff className="size-6" aria-hidden="true" />
              <p className="text-sm">Nothing here yet.</p>
            </div>
          ) : (
            <ul aria-label="Notifications" className="divide-y">
              {items.map((n) => {
                const href = notificationHref(n, role);
                const body = (
                  <>
                    <span className="flex items-start gap-2">
                      {n.read_at === null && (
                        <span
                          aria-hidden="true"
                          className="mt-1.5 size-2 shrink-0 rounded-full bg-primary"
                        />
                      )}
                      <span className={cn("block", n.read_at === null && "font-medium")}>
                        {n.title}
                        {n.read_at === null && <span className="sr-only"> (unread)</span>}
                      </span>
                    </span>
                    <span className="block text-xs text-muted-foreground">
                      {formatDateTime(n.created_at)}
                    </span>
                  </>
                );
                return (
                  <li key={n.id} className="py-1">
                    {href ? (
                      <Link
                        href={href}
                        onClick={() => openItem(n)}
                        className="block space-y-1 rounded-lg px-2 py-2.5 hover:bg-accent/60 focus-visible:ring-[3px] focus-visible:ring-ring/50 focus-visible:outline-none"
                      >
                        {body}
                      </Link>
                    ) : (
                      <div className="space-y-1 px-2 py-2.5">{body}</div>
                    )}
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      </SheetContent>
    </Sheet>
  );
}
