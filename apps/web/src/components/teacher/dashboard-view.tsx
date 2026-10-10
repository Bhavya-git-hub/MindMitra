"use client";

import { ChartLine, HeartHandshake, Inbox, ShieldCheck } from "lucide-react";
import Link from "next/link";
import * as React from "react";

import { SectionCard } from "@/components/cards/section-card";
import { StatCard } from "@/components/cards/stat-card";
import { PageHeader } from "@/components/layout/page-header";
import { DataView } from "@/components/student/data-view";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useAuth } from "@/lib/auth/auth-context";
import { firstName } from "@/lib/format";
import { useQuery } from "@/lib/hooks/use-query";
import { useTeacherApi } from "@/lib/hooks/use-teacher-api";

import { PrivacyNote } from "./shared";

export function TeacherDashboardView() {
  const api = useTeacherApi();
  const { user } = useAuth();
  const dash = useQuery("teacher-dashboard", () => api.dashboard());

  return (
    <>
      <PageHeader
        title={user ? `Welcome, ${firstName(user.full_name)}` : "Welcome"}
        description="How your students are doing as a group, and where you can help."
        actions={
          <DataView query={dash} skeleton={null}>
            {(d) => <Badge variant="accent">{d.teacher.department_name}</Badge>}
          </DataView>
        }
      />
      <DataView query={dash}>
        {(d) => {
          const openReferrals = d.referrals.received + d.referrals.in_progress;
          return (
            <>
              <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
                <StatCard
                  label="Your classes"
                  value={d.classes.length}
                  hint="This term"
                  icon={ChartLine}
                />
                <StatCard
                  label="Students sharing (department)"
                  value={d.department.students_contributing ?? "Not enough yet"}
                  hint="Ranges only, to protect privacy"
                  icon={ShieldCheck}
                />
                <StatCard
                  label="Open referrals"
                  value={openReferrals}
                  hint={`${d.referrals.closed} closed`}
                  icon={HeartHandshake}
                />
                <StatCard
                  label="Student requests"
                  value={d.open_support_requests}
                  hint={
                    d.new_support_requests > 0
                      ? `${d.new_support_requests} waiting for you`
                      : "Nothing waiting"
                  }
                  icon={Inbox}
                />
              </div>

              <SectionCard
                title="Your department this month"
                description="From students who chose to share anonymous summaries."
                action={
                  <Button asChild variant="outline" size="sm">
                    <Link href="/teacher/trends">See trends</Link>
                  </Button>
                }
              >
                <ul className="space-y-2">
                  {d.department.headline.map((line) => (
                    <li key={line}>{line}</li>
                  ))}
                </ul>
                {d.department.actions.length > 0 && (
                  <div className="mt-4 space-y-2 border-t pt-4">
                    <p className="text-sm font-medium">Supportive next steps</p>
                    <ul className="space-y-2 text-sm text-muted-foreground">
                      {d.department.actions.slice(0, 2).map((a) => (
                        <li key={a.key}>
                          <span className="font-medium text-foreground">{a.title}.</span>{" "}
                          {a.message}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              </SectionCard>

              <SectionCard
                title="Your classes"
                description="Open one to see its trends or to refer a student."
              >
                {d.classes.length === 0 ? (
                  <p className="text-sm text-muted-foreground">
                    No classes are set up for you this term.
                  </p>
                ) : (
                  <ul className="divide-y">
                    {d.classes.map((c) => (
                      <li
                        key={c.id}
                        className="flex flex-wrap items-center justify-between gap-2 py-3"
                      >
                        <div>
                          <Link
                            href={`/teacher/classes/${c.id}`}
                            className="font-medium underline-offset-4 hover:underline"
                          >
                            {c.title}
                          </Link>
                          <p className="text-sm text-muted-foreground">
                            {c.code} · {c.term} · {c.enrolled} enrolled
                          </p>
                        </div>
                      </li>
                    ))}
                  </ul>
                )}
              </SectionCard>

              <PrivacyNote>
                You see groups, never individuals. A figure appears only when enough students
                contribute that nobody could be picked out. Students who want your help can ask you
                directly, and you can ask the wellbeing team to reach out to a student in your
                class. Therapy notes, journals, private conversations and diagnoses are never shown
                to teachers.
              </PrivacyNote>
            </>
          );
        }}
      </DataView>
    </>
  );
}
