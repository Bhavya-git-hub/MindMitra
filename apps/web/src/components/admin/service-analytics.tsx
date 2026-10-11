"use client";

import { CalendarCheck, Percent, ThumbsUp, UserX, Users } from "lucide-react";
import * as React from "react";

import { SectionCard } from "@/components/cards/section-card";
import { StatCard } from "@/components/cards/stat-card";
import { BarSeriesChart, TrendChart, type ChartDatum } from "@/components/charts";
import { LoadingState } from "@/components/states/loading-state";
import { DataView } from "@/components/student/data-view";
import type {
  EngagementGroup,
  ServiceAnalytics,
  ShareState,
  UsageWeek,
  UtilisationWeek,
} from "@/lib/api/admin-schemas";
import { MODE_LABELS, formatShortDate, titleCase } from "@/lib/format";
import type { QueryResult } from "@/lib/hooks/use-query";

import { Table } from "./shared";

/** What stands in for a number from 1 to 4 (the API sends `null`, never the number). */
export const FEWER_THAN_5 = "Fewer than 5";
export const TOO_FEW_PEOPLE = "Too few people to show";

/** A count, or the words for a hidden one. */
export const countText = (n: number | null) => (n === null ? FEWER_THAN_5 : String(n));

/** One chart row per item. A hidden (`null`) value is left out, so the chart shows a gap. */
function chartRows<T>(
  items: T[],
  xKey: string,
  label: (item: T) => string,
  fields: Record<string, (item: T) => number | null>,
): ChartDatum[] {
  return items.map((item) => {
    const datum: ChartDatum = { [xKey]: label(item) };
    for (const [key, read] of Object.entries(fields)) {
      const value = read(item);
      if (value !== null) datum[key] = value;
    }
    return datum;
  });
}

/** One chart row per finished week. */
export function weekRows<T extends { week_start: string }>(
  rows: T[],
  fields: Record<string, (row: T) => number | null>,
): ChartDatum[] {
  return chartRows(rows, "week", (row) => formatShortDate(row.week_start), fields);
}

function shareText(share: ShareState): string {
  switch (share.state) {
    case "shown":
      return `About ${share.percent}%`;
    case "few":
      return "A few";
    case "most":
      return "Nearly all";
    case "hidden":
      return "Not enough people";
  }
}

const SOURCE_LABELS: Record<string, string> = {
  rule: "Rule-based",
  model: "Model-based",
  therapist: "Made by a therapist",
};

type Hours = { booked_hours: number | null; utilisation_percent: number | null };

function percentText(figures: Hours): string {
  if (figures.booked_hours === null) return FEWER_THAN_5;
  return figures.utilisation_percent === null
    ? "No hours offered"
    : `${figures.utilisation_percent}%`;
}

const hoursText = (n: number | null) => (n === null ? FEWER_THAN_5 : `${n} h`);

// ---- platform usage ------------------------------------------------------------------------

function UsageSection({ a }: { a: ServiceAnalytics }) {
  const { weekly, totals } = a.usage;
  const activity = weekRows<UsageWeek>(weekly, {
    check_ins: (w) => w.check_ins,
    active_students: (w) => w.active_students,
    sign_ins: (w) => w.sign_ins,
  });
  const messages = weekRows<UsageWeek>(weekly, {
    companion_messages: (w) => w.companion_messages,
    therapist_messages: (w) => w.therapist_messages,
  });
  return (
    <SectionCard
      title="Platform usage"
      description="How much the platform was used in each finished week. These are counts only: nothing anyone wrote or said is read."
    >
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3">
        <StatCard label="Check-ins" value={countText(totals.check_ins)} icon={CalendarCheck} />
        <StatCard
          label="Students who logged something"
          value={countText(totals.active_students)}
          hint="Each person counted once"
          icon={Users}
        />
        <StatCard label="Sign-ins" value={countText(totals.sign_ins)} />
        <StatCard
          label="Companion messages sent by students"
          value={countText(totals.companion_messages)}
        />
        <StatCard label="Messages with therapists" value={countText(totals.therapist_messages)} />
      </div>
      <div className="mt-6 grid grid-cols-1 gap-6 lg:grid-cols-2">
        <TrendChart
          title="Check-ins, active students and sign-ins each week"
          description="A week with fewer than 5 has no point and reads “Fewer than 5” in the table."
          data={activity}
          xKey="week"
          series={[
            { key: "check_ins", label: "Check-ins" },
            { key: "active_students", label: "Active students" },
            { key: "sign_ins", label: "Sign-ins" },
          ]}
          blankLabel={FEWER_THAN_5}
        />
        <TrendChart
          title="Messages each week"
          description="Counted, never read."
          data={messages}
          xKey="week"
          series={[
            { key: "companion_messages", label: "Companion messages" },
            { key: "therapist_messages", label: "Messages with therapists" },
          ]}
          blankLabel={FEWER_THAN_5}
        />
      </div>
    </SectionCard>
  );
}

// ---- counselling utilisation ---------------------------------------------------------------

function UtilisationSection({ a }: { a: ServiceAnalytics }) {
  const { overall, weekly, by_mode: modes } = a.utilisation;
  const nothingOffered = overall.capacity_hours === 0;
  const hours = weekRows<UtilisationWeek>(weekly, {
    capacity_hours: (w) => w.capacity_hours,
    booked_hours: (w) => w.booked_hours,
  });
  const percent = weekRows<UtilisationWeek>(weekly, {
    utilisation_percent: (w) => w.utilisation_percent,
  });
  return (
    <SectionCard
      title="Counselling utilisation"
      description="How much of the time therapists offered was booked, over finished weeks. Percentages are rounded to the nearest 5."
    >
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3">
        <StatCard
          label="Time booked"
          value={percentText(overall)}
          hint={`${hoursText(overall.booked_hours)} of ${overall.capacity_hours} h offered`}
          icon={Percent}
        />
        <StatCard
          label="No-shows"
          value={shareText(overall.no_show_share)}
          hint="of sessions that were due"
          icon={UserX}
        />
        <StatCard
          label="Cancelled appointments"
          value={shareText(overall.cancellation_share)}
          hint="of appointments in this period"
        />
      </div>
      {nothingOffered ? (
        <p className="mt-6 text-sm text-muted-foreground">
          No counselling hours were offered in this period.
        </p>
      ) : (
        <>
          <div className="mt-6 grid grid-cols-1 gap-6 lg:grid-cols-2">
            <BarSeriesChart
              title="Hours offered and booked each week"
              description="A week with fewer than 5 bookings has no booked bar."
              data={hours}
              xKey="week"
              series={[
                { key: "capacity_hours", label: "Hours offered" },
                { key: "booked_hours", label: "Hours booked" },
              ]}
              blankLabel={FEWER_THAN_5}
            />
            <TrendChart
              title="Share of offered time that was booked each week (%)"
              data={percent}
              xKey="week"
              series={[{ key: "utilisation_percent", label: "Booked (%)" }]}
              yDomain={[0, 100]}
              blankLabel={FEWER_THAN_5}
            />
          </div>
          <div className="mt-6">
            <Table
              caption="Counselling utilisation by session type"
              head={[
                "Session type",
                "Hours offered",
                "Hours booked",
                "Booked",
                "No-shows",
                "Cancelled",
              ]}
              minWidth="38rem"
            >
              {modes.map((m) => (
                <tr key={m.mode}>
                  <th scope="row" className="py-2 pr-4 font-normal">
                    {MODE_LABELS[m.mode] ?? titleCase(m.mode)}
                  </th>
                  <td className="py-2 pr-4">{m.capacity_hours}</td>
                  <td className="py-2 pr-4">
                    {m.booked_hours === null ? FEWER_THAN_5 : m.booked_hours}
                  </td>
                  <td className="py-2 pr-4">{percentText(m)}</td>
                  <td className="py-2 pr-4">{shareText(m.no_show_share)}</td>
                  <td className="py-2 pr-4">{shareText(m.cancellation_share)}</td>
                </tr>
              ))}
            </Table>
          </div>
        </>
      )}
    </SectionCard>
  );
}

// ---- intervention engagement ---------------------------------------------------------------

function GroupTable({
  caption,
  firstHead,
  groups,
  label,
}: {
  caption: string;
  firstHead: string;
  groups: EngagementGroup[];
  label: (key: string) => string;
}) {
  return (
    <Table
      caption={caption}
      head={[firstHead, "Suggested", "Viewed", "Completed", "Dismissed", "Helpful", "Not helpful"]}
      minWidth="40rem"
    >
      {groups.map((g) => (
        <tr key={g.key}>
          <th scope="row" className="py-2 pr-4 font-normal">
            {label(g.key)}
          </th>
          {g.suppressed ? (
            <td colSpan={6} className="py-2 pr-4 text-muted-foreground">
              {TOO_FEW_PEOPLE}
            </td>
          ) : (
            [g.suggestions, g.viewed, g.completed, g.dismissed, g.helpful, g.not_helpful].map(
              (n, i) => (
                <td key={i} className="py-2 pr-4">
                  {countText(n)}
                </td>
              ),
            )
          )}
        </tr>
      ))}
    </Table>
  );
}

function EngagementSection({ a }: { a: ServiceAnalytics }) {
  const e = a.engagement;
  const shown = e.by_problem_area.filter((g) => !g.suppressed);
  const bars = chartRows(shown, "area", (g) => titleCase(g.key), {
    suggestions: (g) => g.suggestions,
    completed: (g) => g.completed,
    helpful: (g) => g.helpful,
  });
  return (
    <SectionCard
      title="Intervention engagement"
      description="What happened to the wellbeing suggestions made in this period. A group appears only when at least 5 different students are in it; no student or suggestion text is shown."
    >
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <StatCard
          label="Students who finished a suggestion"
          value={shareText(e.completion_share)}
          hint="of students who received one"
          icon={CalendarCheck}
        />
        <StatCard
          label="Students who found one helpful"
          value={shareText(e.helpful_share)}
          hint="of students who gave feedback"
          icon={ThumbsUp}
        />
      </div>
      <div className="mt-6">
        {bars.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            {TOO_FEW_PEOPLE}: no problem area has 5 different students yet.
          </p>
        ) : (
          <BarSeriesChart
            title="Suggestions by problem area"
            description="Areas with fewer than 5 students are left out."
            data={bars}
            xKey="area"
            series={[
              { key: "suggestions", label: "Suggested" },
              { key: "completed", label: "Completed" },
              { key: "helpful", label: "Found helpful" },
            ]}
            blankLabel={FEWER_THAN_5}
          />
        )}
      </div>
      <div className="mt-6 grid grid-cols-1 gap-6">
        <GroupTable
          caption="Engagement by problem area"
          firstHead="Problem area"
          groups={e.by_problem_area}
          label={titleCase}
        />
        <GroupTable
          caption="Engagement by where the suggestion came from"
          firstHead="Source"
          groups={e.by_source}
          label={(key) => SOURCE_LABELS[key] ?? titleCase(key)}
        />
      </div>
      <div className="mt-6">
        <h3 className="text-sm font-medium">Most used suggestions</h3>
        {e.top_interventions.length === 0 ? (
          <p className="mt-1 text-sm text-muted-foreground">
            No single suggestion has reached 5 students yet.
          </p>
        ) : (
          <ul className="mt-1 space-y-1 text-sm">
            {e.top_interventions.map((t) => (
              <li key={t.intervention_key}>
                {titleCase(t.intervention_key)}:{" "}
                <span className="font-medium">at least {t.students} students</span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </SectionCard>
  );
}

/** The three service sections, loaded separately so a failure here never hides the rest. */
export function ServiceAnalyticsSections({ query }: { query: QueryResult<ServiceAnalytics> }) {
  return (
    <DataView query={query} skeleton={<LoadingState label="Loading service figures…" />}>
      {(a) => (
        <>
          <UsageSection a={a} />
          <UtilisationSection a={a} />
          <EngagementSection a={a} />
          <p className="text-sm text-muted-foreground">{a.disclaimer}</p>
        </>
      )}
    </DataView>
  );
}
