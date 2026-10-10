"use client";

import { BadgeCheck, BellRing, FileText, Lock, ShieldAlert, Users } from "lucide-react";
import Link from "next/link";
import * as React from "react";

import { SectionCard } from "@/components/cards/section-card";
import { StatCard } from "@/components/cards/stat-card";
import { PageHeader } from "@/components/layout/page-header";
import { DataView } from "@/components/student/data-view";
import { Button } from "@/components/ui/button";
import { useAuth } from "@/lib/auth/auth-context";
import { firstName } from "@/lib/format";
import { useAdminApi } from "@/lib/hooks/use-admin-api";
import { useQuery } from "@/lib/hooks/use-query";

import { ROLE_LABELS, Table } from "./shared";

export function PrivacyReminder() {
  return (
    <p className="flex items-start gap-2 text-sm text-muted-foreground">
      <Lock className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
      <span>
        Administrators run the institution but cannot read what students write or what therapists
        record. Therapy notes, journals, private messages and companion conversations are never
        shown here, and figures about groups hide small numbers.
      </span>
    </p>
  );
}

export function AdminDashboardView() {
  const api = useAdminApi();
  const { user } = useAuth();
  const dash = useQuery("admin-dashboard", () => api.dashboard());

  return (
    <>
      <PageHeader
        title={user ? `Welcome, ${firstName(user.full_name)}` : "Welcome"}
        description="Accounts, verification and the health of the service, at a glance."
      />
      <DataView query={dash}>
        {(d) => {
          const people = d.accounts.reduce((n, a) => n + a.active, 0);
          const invited = d.accounts.reduce((n, a) => n + a.invited, 0);
          return (
            <>
              <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3">
                <StatCard
                  label="Active people"
                  value={people}
                  hint={invited > 0 ? `${invited} invited, not yet set up` : "Everyone has set up"}
                  icon={Users}
                />
                <StatCard
                  label="Therapists to verify"
                  value={d.pending_verifications}
                  hint={
                    d.licences_expiring > 0
                      ? `${d.licences_expiring} licence(s) expire within 30 days`
                      : "No licences expiring soon"
                  }
                  icon={BadgeCheck}
                />
                <StatCard
                  label="Draft resources"
                  value={d.draft_resources}
                  hint="Not yet visible to anyone"
                  icon={FileText}
                />
                <StatCard
                  label="Safety alerts waiting"
                  value={d.alerts_awaiting}
                  hint={
                    d.alerts_overdue > 0
                      ? `${d.alerts_overdue} past the response time you set`
                      : "None past the response time"
                  }
                  icon={BellRing}
                />
                <StatCard
                  label="Refused requests (7 days)"
                  value={d.denied_last_7_days}
                  hint="People trying something they may not do"
                  icon={ShieldAlert}
                />
              </div>

              <SectionCard
                title="People by role"
                description="Accounts in your institution."
                action={
                  <Button asChild variant="outline" size="sm">
                    <Link href="/admin/users">Manage people</Link>
                  </Button>
                }
              >
                <Table
                  caption="Accounts by role and status"
                  head={["Role", "Active", "Invited", "Suspended"]}
                  minWidth="22rem"
                >
                  {d.accounts.map((a) => (
                    <tr key={a.role}>
                      <th scope="row" className="py-2 pr-4 font-normal">
                        {ROLE_LABELS[a.role] ?? a.role}
                      </th>
                      <td className="py-2 pr-4">{a.active}</td>
                      <td className="py-2 pr-4">{a.invited}</td>
                      <td className="py-2 pr-4">{a.suspended}</td>
                    </tr>
                  ))}
                </Table>
              </SectionCard>

              <SectionCard title="Where to next">
                <ul className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                  {[
                    ["/admin/therapists", "Verify therapists", "Check professional registration."],
                    ["/admin/academics", "Departments and courses", "Set up the academic year."],
                    ["/admin/appointments", "Appointment oversight", "How booking is going."],
                    ["/admin/resources", "Resources", "Review the self-help library."],
                    ["/admin/analytics", "Analytics", "Anonymous trends across the institution."],
                    ["/admin/audit", "Audit log", "Who did what, and when."],
                    ["/admin/settings", "Settings", "Notifications, safety and contacts."],
                  ].map(([href, title, text]) => (
                    <li key={href}>
                      <Link
                        href={href as string}
                        className="block rounded-lg border p-3 transition-colors hover:bg-secondary"
                      >
                        <span className="font-medium">{title}</span>
                        <span className="block text-sm text-muted-foreground">{text}</span>
                      </Link>
                    </li>
                  ))}
                </ul>
              </SectionCard>
              <PrivacyReminder />
            </>
          );
        }}
      </DataView>
    </>
  );
}
