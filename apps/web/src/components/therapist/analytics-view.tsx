"use client";

import { BarChart3 } from "lucide-react";
import * as React from "react";

import { SectionCard } from "@/components/cards/section-card";
import { StatCard } from "@/components/cards/stat-card";
import {
  BarSeriesChart,
  DonutChart,
  TrendChart,
  type ChartDatum,
  type Slice,
} from "@/components/charts";
import { PageHeader } from "@/components/layout/page-header";
import { EmptyState } from "@/components/states/empty-state";
import { DataView } from "@/components/student/data-view";
import { WindowTabs } from "@/components/teacher/shared";
import type { TherapistAnalytics } from "@/lib/api/therapist-schemas";
import type { WindowWeeks } from "@/lib/api/teacher-schemas";
import { formatDuration, formatShortDate, modeLabel, titleCase } from "@/lib/format";
import { useQuery } from "@/lib/hooks/use-query";
import { useTherapistApi } from "@/lib/hooks/use-therapist-api";

import { RequireVerified, SEVERITY_LABELS } from "./shared";

type Caseload = TherapistAnalytics["caseload"];
type Appointments = TherapistAnalytics["appointments"];
type Interventions = TherapistAnalytics["interventions"];
type Alerts = TherapistAnalytics["alerts"];

const RECOMMENDATION_LABELS: Record<string, string> = {
  pending: "Not seen yet",
  viewed: "Seen",
  dismissed: "Set aside",
  completed: "Done",
};
const FOLLOW_UP_LABELS: Record<string, string> = {
  open: "Open",
  done: "Done",
  cancelled: "Cancelled",
};
const FOLLOW_UP_KIND_LABELS: Record<string, string> = {
  check_in: "Check in",
  book_session: "Book a session",
  referral: "Referral",
  paperwork: "Paperwork",
  other: "Other",
};
const ALERT_STATUS_LABELS: Record<string, string> = {
  open: "Waiting",
  acknowledged: "Seen",
  escalated: "Passed on",
  in_progress: "Being followed up",
  resolved: "Resolved",
  dismissed: "Dismissed",
};
const SEVERITY_ORDER = ["imminent", "high", "moderate", "low"];

const sum = (values: Iterable<number>) => [...values].reduce((a, b) => a + b, 0);
const percent = (value: number | null) => (value === null ? "—" : `${value}%`);
const oneDecimal = (value: number) => Math.round(value * 10) / 10;

/** Rows for a chart with one point per week; a week with no figure simply has no value. */
function weekRows<T extends { week_start: string }>(
  weeks: T[],
  fields: Record<string, (week: T) => number | null>,
): ChartDatum[] {
  return weeks.map((week) => {
    const row: ChartDatum = { week: formatShortDate(week.week_start) };
    for (const [key, pick] of Object.entries(fields)) {
      const value = pick(week);
      if (value !== null) row[key] = oneDecimal(value);
    }
    return row;
  });
}

const hasValue = (rows: ChartDatum[], key: string) => rows.some((row) => key in row);

function Note({ children }: { children: React.ReactNode }) {
  return <p className="text-sm text-muted-foreground">{children}</p>;
}

function CaseloadSection({ data }: { data: Caseload }) {
  const rows = weekRows(data.weekly, {
    mood: (w) => w.mood_avg,
    stress: (w) => w.stress_avg,
    sleep: (w) => w.sleep_hours_avg,
  });
  const lastWeek = data.weekly[data.weekly.length - 1];
  const showsWellbeing = hasValue(rows, "mood") || hasValue(rows, "stress");
  const showsSleep = hasValue(rows, "sleep");
  return (
    <SectionCard
      title="Your caseload"
      description="Averages from students on your caseload who share their check-ins with you. Each student's own weekly average counts once, and no one is named."
    >
      <div className="grid gap-4 sm:grid-cols-3">
        <StatCard label="On your caseload" value={data.caseload_size} />
        <StatCard
          label="Sharing check-ins"
          value={data.sharing_count}
          hint={
            data.caseload_size === 0
              ? "No students yet"
              : `of ${data.caseload_size} on your caseload`
          }
        />
        <StatCard
          label="Reporting last week"
          value={lastWeek ? lastWeek.students_reporting : 0}
          hint="Students with a check-in, stress or sleep entry"
        />
      </div>
      {data.sharing_count === 0 ? (
        <EmptyState
          icon={BarChart3}
          title="No shared check-ins yet"
          description="Averages appear once a student on your caseload chooses to share their check-ins with their care team. Students can change this at any time."
        />
      ) : !showsWellbeing && !showsSleep ? (
        <EmptyState
          icon={BarChart3}
          title="No check-ins in these weeks"
          description="Nothing was shared in the weeks shown, so there is nothing to average."
        />
      ) : (
        <div className="grid gap-6 lg:grid-cols-2">
          {showsWellbeing && (
            <TrendChart
              title="Mood and stress by week"
              description="Average self-reported score from 1 to 5."
              data={rows}
              xKey="week"
              series={[
                { key: "mood", label: "Mood" },
                { key: "stress", label: "Stress" },
              ]}
              yDomain={[1, 5]}
            />
          )}
          {showsSleep && (
            <TrendChart
              title="Sleep by week"
              description="Average hours of sleep per night."
              data={rows}
              xKey="week"
              series={[{ key: "sleep", label: "Sleep (hours)" }]}
            />
          )}
        </div>
      )}
    </SectionCard>
  );
}

function AppointmentsSection({ data }: { data: Appointments }) {
  const total = sum(Object.values(data.by_status));
  const finished = sum(
    ["completed", "no_show", "cancelled"].map((status) => data.by_status[status] ?? 0),
  );
  const rows = weekRows(data.weekly, {
    scheduled: (w) => w.scheduled,
    completed: (w) => w.completed,
    no_show: (w) => w.no_show,
    cancelled: (w) => w.cancelled,
  });
  const modes = Object.entries(data.by_mode).filter(([, n]) => n > 0);
  return (
    <SectionCard title="Appointments" description="Your appointments that started in these weeks.">
      {total === 0 ? (
        <EmptyState
          icon={BarChart3}
          title="No appointments in these weeks"
          description="Counts appear here once you have appointments in the weeks shown."
        />
      ) : (
        <>
          <div className="grid gap-4 sm:grid-cols-3">
            <StatCard
              label="Completed"
              value={percent(data.rates.completion)}
              hint={finished === 0 ? "Nothing has finished yet" : `of ${finished} that finished`}
            />
            <StatCard
              label="Did not attend"
              value={percent(data.rates.no_show)}
              hint={finished === 0 ? "Nothing has finished yet" : `of ${finished} that finished`}
            />
            <StatCard
              label="Cancelled"
              value={percent(data.rates.cancellation)}
              hint={finished === 0 ? "Nothing has finished yet" : `of ${finished} that finished`}
            />
          </div>
          <BarSeriesChart
            title="Appointments each week"
            description="All appointments that week, and how many were completed, missed or cancelled."
            data={rows}
            xKey="week"
            series={[
              { key: "scheduled", label: "All" },
              { key: "completed", label: "Completed" },
              { key: "no_show", label: "Did not attend" },
              { key: "cancelled", label: "Cancelled" },
            ]}
          />
          {modes.length > 0 && (
            <Note>
              How you met: {modes.map(([mode, n]) => `${modeLabel(mode)} ${n}`).join(" · ")}
            </Note>
          )}
        </>
      )}
    </SectionCard>
  );
}

function slices(counts: Record<string, number>, labels: Record<string, string>): Slice[] {
  return Object.entries(labels).map(([key, name]) => ({ name, value: counts[key] ?? 0 }));
}

function InterventionsSection({ data }: { data: Interventions }) {
  const { recommendations: recs, follow_ups: follow } = data;
  const kinds = Object.entries(follow.by_kind).filter(([, n]) => n > 0);
  return (
    <SectionCard
      title="Interventions"
      description="How the suggestions and follow-ups you set up in these weeks are going. Only counts are shown, never what they say."
    >
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <StatCard label="Suggestions sent" value={recs.total} />
        <StatCard
          label="Suggestions completed"
          value={percent(recs.completion_rate)}
          hint={recs.total === 0 ? "None sent yet" : "of those you sent"}
        />
        <StatCard
          label="Follow-ups past due"
          value={follow.overdue}
          hint={follow.overdue === 0 ? "Nothing is overdue" : "Still open after the due date"}
        />
        <StatCard
          label="Finished on time"
          value={percent(follow.done_on_time_rate)}
          hint={follow.done_on_time_rate === null ? "None finished yet" : "of finished follow-ups"}
        />
      </div>
      <div className="grid gap-6 lg:grid-cols-2">
        <div className="space-y-3">
          {recs.total === 0 ? (
            <Note>You have not sent any suggestions in these weeks.</Note>
          ) : (
            <DonutChart
              title="Suggestions by progress"
              description="Where the suggestions you sent stand with students."
              data={slices(recs.by_status, RECOMMENDATION_LABELS)}
            />
          )}
        </div>
        <div className="space-y-3">
          {follow.total === 0 ? (
            <Note>You have not set any follow-ups in these weeks.</Note>
          ) : (
            <>
              <DonutChart
                title="Follow-ups by progress"
                description="The follow-ups you set for yourself."
                data={slices(follow.by_status, FOLLOW_UP_LABELS)}
              />
              {kinds.length > 0 && (
                <Note>
                  By type:{" "}
                  {kinds
                    .map(([kind, n]) => `${FOLLOW_UP_KIND_LABELS[kind] ?? titleCase(kind)} ${n}`)
                    .join(" · ")}
                </Note>
              )}
            </>
          )}
        </div>
      </div>
    </SectionCard>
  );
}

function AlertsSection({ data }: { data: Alerts }) {
  const rows = weekRows(data.weekly, { raised: (w) => w.count });
  const minutes = data.acknowledged_median_minutes;
  return (
    <SectionCard
      title="Risk alerts"
      description="Alerts that were yours or the counselling team's in these weeks. An alert is a prompt to reach out, never a conclusion about a student."
    >
      {data.total === 0 ? (
        <EmptyState
          icon={BarChart3}
          title="No alerts in these weeks"
          description="Counts appear here when alerts are raised."
        />
      ) : (
        <>
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            <StatCard label="Raised" value={data.total} />
            <StatCard
              label="Typical time to respond"
              value={minutes === null ? "—" : formatDuration(Math.round(minutes))}
              hint={minutes === null ? "None acknowledged yet" : "Median until acknowledged"}
            />
            <StatCard
              label="Past response time"
              value={data.overdue_open}
              hint={data.overdue_open === 0 ? "None waiting too long" : "Still waiting to be seen"}
            />
            <StatCard label="Resolved" value={data.resolved_count} />
          </div>
          <div className="grid gap-6 lg:grid-cols-2">
            <BarSeriesChart
              title="Alerts raised each week"
              data={rows}
              xKey="week"
              series={[{ key: "raised", label: "Raised" }]}
            />
            <div className="space-y-3">
              <DonutChart
                title="Alerts by priority"
                data={SEVERITY_ORDER.map((key) => ({
                  name: SEVERITY_LABELS[key] ?? titleCase(key),
                  value: data.by_severity[key] ?? 0,
                }))}
              />
              <Note>
                By status:{" "}
                {Object.entries(ALERT_STATUS_LABELS)
                  .map(([key, label]) => `${label} ${data.by_status[key] ?? 0}`)
                  .join(" · ")}
              </Note>
            </div>
          </div>
        </>
      )}
    </SectionCard>
  );
}

function AnalyticsBody() {
  const api = useTherapistApi();
  const [weeks, setWeeks] = React.useState<WindowWeeks>(8);
  const query = useQuery(`therapist-analytics-${weeks}`, () => api.analytics(weeks));

  return (
    <>
      <WindowTabs value={weeks} onChange={setWeeks} />
      <DataView query={query}>
        {(a) => (
          <>
            <CaseloadSection data={a.caseload} />
            <AppointmentsSection data={a.appointments} />
            <InterventionsSection data={a.interventions} />
            <AlertsSection data={a.alerts} />
            <p className="text-sm text-muted-foreground">
              {a.disclaimer} Showing the {a.weeks} finished weeks from{" "}
              {formatShortDate(a.window_start)} to {formatShortDate(a.window_end)}.
            </p>
          </>
        )}
      </DataView>
    </>
  );
}

export function AnalyticsView() {
  return (
    <>
      <PageHeader
        title="Analytics"
        description="How your caseload and your own work have been going. Counts and averages only, from finished weeks."
      />
      <RequireVerified>
        <AnalyticsBody />
      </RequireVerified>
    </>
  );
}
