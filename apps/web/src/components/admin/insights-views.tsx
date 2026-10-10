"use client";

import { CalendarClock, Clock3, Hourglass } from "lucide-react";
import * as React from "react";

import { SectionCard } from "@/components/cards/section-card";
import { StatCard } from "@/components/cards/stat-card";
import { PageHeader } from "@/components/layout/page-header";
import { DataView } from "@/components/student/data-view";
import { AnalyticsPanel } from "@/components/teacher/analytics-panel";
import { WindowTabs } from "@/components/teacher/shared";
import type { WeekCount } from "@/lib/api/admin-schemas";
import type { WindowWeeks } from "@/lib/api/teacher-schemas";
import { formatShortDate, titleCase } from "@/lib/format";
import { useAdminApi } from "@/lib/hooks/use-admin-api";
import { useQuery } from "@/lib/hooks/use-query";

import { PrivacyReminder } from "./dashboard-view";
import { ROLE_LABELS, Table } from "./shared";

/** A count, or the words that stand in for a number from 1 to 4. */
const count = (n: number | null) => (n === null ? "Fewer than 5" : String(n));

function WeeklyCounts({
  title,
  caption,
  rows,
}: {
  title: string;
  caption: string;
  rows: WeekCount[];
}) {
  return (
    <SectionCard title={title} description="Weeks that have finished. Small numbers are not shown.">
      <Table caption={caption} head={["Week starting", "Count"]} minWidth="18rem">
        {rows.map((w) => (
          <tr key={w.week_start}>
            <th scope="row" className="py-2 pr-4 font-normal">
              {formatShortDate(w.week_start)}
            </th>
            <td className="py-2 pr-4">{count(w.count)}</td>
          </tr>
        ))}
      </Table>
    </SectionCard>
  );
}

export function AnalyticsView() {
  const api = useAdminApi();
  const [weeks, setWeeks] = React.useState<WindowWeeks>(8);
  const data = useQuery(`admin-analytics-${weeks}`, () => api.analytics(weeks));

  return (
    <>
      <PageHeader
        title="Analytics"
        description="Anonymous trends across the whole institution. No figure can be traced to a person."
      />
      <WindowTabs value={weeks} onChange={setWeeks} />
      <DataView query={data}>
        {(a) => (
          <>
            <SectionCard
              title="Student wellbeing"
              description="From students who chose to share anonymous summaries."
            >
              <AnalyticsPanel analytics={a.wellbeing} />
            </SectionCard>
            <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
              <WeeklyCounts
                title="Appointments booked"
                caption="Appointments booked each week"
                rows={a.appointments_booked}
              />
              <WeeklyCounts
                title="Safety alerts raised"
                caption="Safety alerts raised each week"
                rows={a.alerts_raised}
              />
            </div>
            <SectionCard title="People">
              <Table
                caption="Accounts by role and status"
                head={["Role", "Active", "Invited", "Suspended"]}
                minWidth="22rem"
              >
                {a.accounts.map((r) => (
                  <tr key={r.role}>
                    <th scope="row" className="py-2 pr-4 font-normal">
                      {ROLE_LABELS[r.role] ?? r.role}
                    </th>
                    <td className="py-2 pr-4">{r.active}</td>
                    <td className="py-2 pr-4">{r.invited}</td>
                    <td className="py-2 pr-4">{r.suspended}</td>
                  </tr>
                ))}
              </Table>
            </SectionCard>
            <SectionCard title="Published resources">
              {Object.keys(a.resources_published).length === 0 ? (
                <p className="text-sm text-muted-foreground">Nothing is published yet.</p>
              ) : (
                <ul className="flex flex-wrap gap-x-6 gap-y-1 text-sm">
                  {Object.entries(a.resources_published).map(([type, n]) => (
                    <li key={type}>
                      {titleCase(type)}: <span className="font-medium">{n}</span>
                    </li>
                  ))}
                </ul>
              )}
            </SectionCard>
            <p className="text-sm text-muted-foreground">{a.small_number_note}</p>
            <PrivacyReminder />
          </>
        )}
      </DataView>
    </>
  );
}

export function OversightView() {
  const api = useAdminApi();
  const [weeks, setWeeks] = React.useState<WindowWeeks>(8);
  const data = useQuery(`admin-oversight-${weeks}`, () => api.oversight(weeks));

  return (
    <>
      <PageHeader
        title="Appointment oversight"
        description="How booking is going across the institution. Counts only: who attended and what was discussed stay private."
      />
      <WindowTabs value={weeks} onChange={setWeeks} />
      <DataView query={data}>
        {(o) => (
          <>
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3">
              <StatCard
                label="Confirmed in the next 7 days"
                value={o.confirmed_next_7_days === null ? "Fewer than 5" : o.confirmed_next_7_days}
                icon={CalendarClock}
              />
              <StatCard
                label="Requests waiting over 2 days"
                value={o.stale_requests}
                hint={o.stale_requests > 0 ? "Therapists may need a nudge" : "Nothing is stuck"}
                icon={Hourglass}
              />
              <StatCard
                label="Appointments in this period"
                value={
                  o.by_status.some((s) => s.count === null)
                    ? "Some hidden"
                    : o.by_status.reduce((n, s) => n + (s.count ?? 0), 0)
                }
                hint={`${o.window_weeks} finished weeks`}
                icon={Clock3}
              />
            </div>
            <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
              <SectionCard title="By outcome" description="Small numbers are not shown.">
                <Table
                  caption="Appointments by outcome"
                  head={["Outcome", "Count"]}
                  minWidth="16rem"
                >
                  {o.by_status.map((s) => (
                    <tr key={s.status}>
                      <th scope="row" className="py-2 pr-4 font-normal">
                        {titleCase(s.status)}
                      </th>
                      <td className="py-2 pr-4">{count(s.count)}</td>
                    </tr>
                  ))}
                </Table>
              </SectionCard>
              <WeeklyCounts
                title="Scheduled each week"
                caption="Appointments scheduled each week"
                rows={o.weekly_scheduled}
              />
            </div>
            <SectionCard
              title="Therapist workload"
              description="Helps balance the load. Which students see which therapist is not shown."
            >
              <Table
                caption="Appointments per therapist"
                head={["Therapist", "Coming up", "Completed", "No-shows", "Cancelled"]}
                minWidth="34rem"
              >
                {o.therapists.map((t) => (
                  <tr key={t.therapist_id}>
                    <th scope="row" className="py-2 pr-4 font-normal">
                      {t.full_name}
                    </th>
                    <td className="py-2 pr-4">{t.upcoming}</td>
                    <td className="py-2 pr-4">{t.completed}</td>
                    <td className="py-2 pr-4">{t.no_shows}</td>
                    <td className="py-2 pr-4">{t.cancelled}</td>
                  </tr>
                ))}
              </Table>
            </SectionCard>
            <p className="text-sm text-muted-foreground">{o.note}</p>
          </>
        )}
      </DataView>
    </>
  );
}
