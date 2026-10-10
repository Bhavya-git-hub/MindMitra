"use client";

import {
  Bell,
  CalendarClock,
  CalendarDays,
  ClipboardCheck,
  MessageCircle,
  Users,
} from "lucide-react";
import Link from "next/link";
import * as React from "react";

import { SectionCard } from "@/components/cards/section-card";
import { StatCard } from "@/components/cards/stat-card";
import { PageHeader } from "@/components/layout/page-header";
import { EmptyState } from "@/components/states/empty-state";
import { DataView } from "@/components/student/data-view";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useAuth } from "@/lib/auth/auth-context";
import type { TherapistAppointment } from "@/lib/api/therapist-schemas";
import { formatTime, modeLabel } from "@/lib/format";
import { useQuery } from "@/lib/hooks/use-query";
import { useTherapistApi } from "@/lib/hooks/use-therapist-api";

import { VerificationBadge, VerificationNotice } from "./shared";

function firstName(fullName: string): string {
  return fullName.trim().split(/\s+/)[0] ?? fullName;
}

function TodayRow({ a }: { a: TherapistAppointment }) {
  return (
    <li className="flex flex-wrap items-center justify-between gap-3 py-3">
      <div className="space-y-1">
        <p className="font-medium">
          {formatTime(a.starts_at)} · {a.student_name}
        </p>
        <p className="text-sm text-muted-foreground">{modeLabel(a.mode)}</p>
      </div>
      <div className="flex items-center gap-2">
        <Badge variant={a.status === "confirmed" ? "success" : "info"}>
          {a.status === "confirmed" ? "Confirmed" : "Waiting for you"}
        </Badge>
        {a.can_start && (
          <Button asChild size="sm">
            <Link href="/therapist/appointments">Start session</Link>
          </Button>
        )}
      </div>
    </li>
  );
}

export function DashboardView() {
  const api = useTherapistApi();
  const { user } = useAuth();
  const dash = useQuery("therapist-dashboard", () => api.dashboard());

  return (
    <>
      <PageHeader
        title={user ? `Welcome, ${firstName(user.full_name)}` : "Welcome"}
        description="What needs your attention today."
        actions={
          <DataView query={dash} skeleton={null}>
            {(d) => (
              <VerificationBadge status={d.verification_status} label={d.verification_label} />
            )}
          </DataView>
        }
      />
      <DataView query={dash}>
        {(d) => {
          const urgent = (d.alerts_by_severity.imminent ?? 0) + (d.alerts_by_severity.high ?? 0);
          const open = Object.values(d.alerts_by_severity).reduce((a, b) => a + b, 0);
          return (
            <>
              {!d.can_see_students && <VerificationNotice label={d.verification_label} />}
              <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
                <StatCard
                  label="Requests waiting"
                  value={d.pending_requests}
                  hint={d.pending_requests === 0 ? "All answered" : "Confirm or decline"}
                  icon={CalendarClock}
                />
                <StatCard
                  label="Open alerts"
                  value={open}
                  hint={
                    open === 0
                      ? "Nothing needs reaching out to"
                      : `${urgent} high priority · ${d.alerts_overdue} overdue`
                  }
                  icon={Bell}
                />
                <StatCard
                  label="Follow-ups due"
                  value={d.follow_ups_due_today + d.follow_ups_overdue}
                  hint={`${d.follow_ups_due_today} today · ${d.follow_ups_overdue} overdue`}
                  icon={ClipboardCheck}
                />
                <StatCard
                  label="Unread messages"
                  value={d.unread_messages}
                  hint={d.unread_messages === 0 ? "You're up to date" : "From your students"}
                  icon={MessageCircle}
                />
                <StatCard
                  label="Caseload"
                  value={`${d.caseload} / ${d.max_caseload}`}
                  hint={
                    d.accepting_new_students ? "Taking new students" : "Not taking new students"
                  }
                  icon={Users}
                />
                <StatCard
                  label="Next appointment"
                  value={d.next_appointment ? formatTime(d.next_appointment.starts_at) : "—"}
                  hint={d.next_appointment ? d.next_appointment.student_name : "Nothing confirmed"}
                  icon={CalendarDays}
                />
              </div>
              <SectionCard
                title="Today"
                action={
                  <Button asChild variant="outline" size="sm">
                    <Link href="/therapist/appointments">All appointments</Link>
                  </Button>
                }
              >
                {d.today.length === 0 ? (
                  <EmptyState
                    icon={CalendarDays}
                    title="No appointments today"
                    description="Requests and confirmed sessions for today will show here."
                  />
                ) : (
                  <ul className="divide-y">
                    {d.today.map((a) => (
                      <TodayRow key={a.id} a={a} />
                    ))}
                  </ul>
                )}
              </SectionCard>
            </>
          );
        }}
      </DataView>
    </>
  );
}
