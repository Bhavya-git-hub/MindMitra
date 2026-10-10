"use client";

import { ShieldCheck, Users } from "lucide-react";
import * as React from "react";

import { SectionCard } from "@/components/cards/section-card";
import { StatCard } from "@/components/cards/stat-card";
import { TrendChart, type ChartDatum } from "@/components/charts";
import { EmptyState } from "@/components/states/empty-state";
import { InlineAlert } from "@/components/states/inline-alert";
import type { GroupAnalytics, WeekFigures } from "@/lib/api/teacher-schemas";
import { formatShortDate } from "@/lib/format";

import { ShareText } from "./shared";

const STRESSOR_LABELS: Record<string, string> = {
  exams: "Exams",
  deadlines: "Deadlines",
  workload: "Workload",
  finances: "Money",
  sleep: "Sleep",
  relationships: "Relationships",
  housing: "Housing",
  career: "Career worries",
};

const stressorLabel = (key: string) =>
  STRESSOR_LABELS[key] ?? key.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());

function chartData(weeks: WeekFigures[], fields: Record<string, keyof WeekFigures>): ChartDatum[] {
  return weeks.map((w) => {
    const row: ChartDatum = { week: formatShortDate(w.week_start) };
    for (const [name, field] of Object.entries(fields)) {
      const value = w[field];
      if (typeof value === "number") row[name] = value;
    }
    return row;
  });
}

const hasAny = (rows: ChartDatum[], keys: string[]) => rows.some((r) => keys.some((k) => k in r));

/** What a teacher sees when a group is too small to show: a reason, never a number. */
export function TooSmall({ analytics }: { analytics: GroupAnalytics }) {
  return (
    <EmptyState
      icon={ShieldCheck}
      title="Not enough students to show this group"
      description={`Figures appear once at least ${analytics.min_group_size} students in a group have chosen to share anonymous summaries. This keeps every student unidentifiable, so smaller groups are never shown, even as a rough number.`}
    />
  );
}

function latest(weeks: WeekFigures[], pick: (w: WeekFigures) => number | null) {
  for (let i = weeks.length - 1; i >= 0; i -= 1) {
    const value = pick(weeks[i]!);
    if (value !== null) return value;
  }
  return null;
}

function Headline({ analytics }: { analytics: GroupAnalytics }) {
  const { weeks } = analytics;
  const mood = latest(weeks, (w) => w.mood);
  const stress = latest(weeks, (w) => w.stress);
  const sleep = latest(weeks, (w) => w.sleep_hours);
  const none = "Not enough data";
  return (
    <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
      <StatCard
        label="Students contributing"
        value={analytics.students_contributing ?? "Hidden"}
        hint="Group sizes are shown as ranges"
        icon={Users}
      />
      <StatCard
        label="Average mood"
        value={mood === null ? "—" : `${mood} / 5`}
        hint={mood === null ? none : "Most recent week with enough data"}
      />
      <StatCard
        label="Average stress"
        value={stress === null ? "—" : `${stress} / 5`}
        hint={stress === null ? none : "Most recent week with enough data"}
      />
      <StatCard
        label="Average sleep"
        value={sleep === null ? "—" : `${sleep} h`}
        hint={sleep === null ? none : "A night, most recent week"}
      />
    </div>
  );
}

function WeeklyTable({ weeks }: { weeks: WeekFigures[] }) {
  return (
    <div className="relative overflow-x-auto">
      <table className="w-full min-w-[34rem] text-left text-sm">
        <caption className="sr-only">
          Weekly shares of students. Small numbers of students are described in words, never
          counted.
        </caption>
        <thead>
          <tr className="border-b text-muted-foreground">
            <th scope="col" className="py-2 pr-4 font-medium">
              Week starting
            </th>
            <th scope="col" className="py-2 pr-4 font-medium">
              Students reporting
            </th>
            <th scope="col" className="py-2 pr-4 font-medium">
              Checked in
            </th>
            <th scope="col" className="py-2 pr-4 font-medium">
              Study pressure
            </th>
            <th scope="col" className="py-2 font-medium">
              Signs of strain
            </th>
          </tr>
        </thead>
        <tbody>
          {[...weeks].reverse().map((w) => (
            <tr key={w.week_start} className="border-b last:border-0">
              <th scope="row" className="py-2 pr-4 font-normal">
                {formatShortDate(w.week_start)}
              </th>
              <td className="py-2 pr-4">{w.students_reporting ?? "Not enough"}</td>
              <td className="py-2 pr-4">
                <ShareText share={w.check_in} />
              </td>
              <td className="py-2 pr-4">
                <ShareText share={w.academic_stress} />
              </td>
              <td className="py-2">
                <ShareText share={w.strain} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/**
 * Wellness, academic-stress and strain trends for one group. Every number here already passed
 * the server's privacy rules; the component only chooses how to show them, and shows a plain
 * message in place of anything the server withheld.
 */
export function AnalyticsPanel({ analytics }: { analytics: GroupAnalytics }) {
  if (analytics.state === "too_small") return <TooSmall analytics={analytics} />;

  const moodData = chartData(analytics.weeks, {
    mood: "mood",
    energy: "energy",
    stress: "stress",
  });
  const sleepData = chartData(analytics.weeks, { sleep: "sleep_hours" });

  return (
    <div className="space-y-6">
      <Headline analytics={analytics} />

      {analytics.actions.length > 0 && (
        <SectionCard
          title="Supportive next steps"
          description="Ideas for the group as a whole, based on the last few weeks."
        >
          <ul className="space-y-3">
            {analytics.actions.map((a) => (
              <li key={a.key}>
                <p className="font-medium">{a.title}</p>
                <p className="text-sm text-muted-foreground">{a.message}</p>
              </li>
            ))}
          </ul>
        </SectionCard>
      )}

      <SectionCard
        title="Wellness trends"
        description="Weekly averages from students who shared. A gap means too few students reported that week."
      >
        {hasAny(moodData, ["mood", "energy", "stress"]) ? (
          <TrendChart
            title="Mood, energy and stress (1 to 5)"
            data={moodData}
            xKey="week"
            yDomain={[1, 5]}
            series={[
              { key: "mood", label: "Mood" },
              { key: "energy", label: "Energy" },
              { key: "stress", label: "Stress" },
            ]}
          />
        ) : (
          <p className="text-sm text-muted-foreground">
            No week in this window has enough students to show an average yet.
          </p>
        )}
        {hasAny(sleepData, ["sleep"]) && (
          <div className="mt-6">
            <TrendChart
              title="Average sleep (hours a night)"
              data={sleepData}
              xKey="week"
              series={[{ key: "sleep", label: "Sleep" }]}
              height={200}
            />
          </div>
        )}
      </SectionCard>

      <SectionCard
        title="Academic stress and burnout signs"
        description="Shares of students, rounded to the nearest 5%. Small groups are described in words."
      >
        <WeeklyTable weeks={analytics.weeks} />
        <p className="mt-4 text-sm text-muted-foreground">{analytics.strain_explainer}</p>
      </SectionCard>

      {analytics.stressors.length > 0 && (
        <SectionCard
          title="What students name as stressors"
          description="Among students who did a stress check in this window."
        >
          <ul className="grid gap-2 sm:grid-cols-2">
            {analytics.stressors.map((s) => (
              <li
                key={s.key}
                className="flex items-center justify-between gap-3 rounded-lg border p-3"
              >
                <span>{stressorLabel(s.key)}</span>
                <span className="text-sm text-muted-foreground">
                  <ShareText share={s.share} />
                </span>
              </li>
            ))}
          </ul>
        </SectionCard>
      )}

      {analytics.wellbeing.length > 0 && (
        <SectionCard
          title="Wellbeing check results"
          description="Where students' latest wellbeing questionnaire in this window falls. A group-level view, not an assessment."
        >
          <ul className="grid gap-2 sm:grid-cols-3">
            {analytics.wellbeing.map((b) => (
              <li key={b.key} className="rounded-lg border p-3">
                <p className="font-medium">{b.label}</p>
                <p className="text-sm text-muted-foreground">
                  <ShareText share={b.share} />
                </p>
              </li>
            ))}
          </ul>
        </SectionCard>
      )}

      <InlineAlert tone="info" title="How to read this">
        {analytics.disclaimer}
      </InlineAlert>
    </div>
  );
}
