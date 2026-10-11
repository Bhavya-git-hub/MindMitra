"use client";

import { ClipboardCheck, ListChecks, Target, TrendingUp } from "lucide-react";
import Link from "next/link";

import { StatCard } from "@/components/cards/stat-card";
import { SectionCard } from "@/components/cards/section-card";
import { BarSeriesChart, TrendChart, type ChartDatum } from "@/components/charts";
import { DataView } from "@/components/student/data-view";
import { Button } from "@/components/ui/button";
import type { AnalyticsWeek, WellnessAnalytics } from "@/lib/api/student-schemas";
import { formatShortDate } from "@/lib/format";
import { useQuery, type QueryResult } from "@/lib/hooks/use-query";
import { useStudentApi } from "@/lib/hooks/use-student-api";
import { GOAL_CATEGORY_LABELS } from "@/lib/student-options";

/** How many weeks the student pages look back (the API accepts 4 to 12). */
export const ANALYTICS_WEEKS = 8;

export function useWellnessAnalytics(): QueryResult<WellnessAnalytics> {
  const api = useStudentApi();
  return useQuery(`wellness-analytics-${ANALYTICS_WEEKS}`, () =>
    api.wellnessAnalytics(ANALYTICS_WEEKS),
  );
}

/** "6 Oct", with "(so far)" on the week that is still going. */
function weekLabel(weekStart: string, partial: boolean): string {
  const label = formatShortDate(weekStart);
  return partial ? `${label} (so far)` : label;
}

const loading = (text: string) => <p className="text-sm text-muted-foreground">{text}</p>;

function indexRows(weeks: AnalyticsWeek[]): ChartDatum[] {
  return weeks.map((w) => {
    const row: ChartDatum = { week: weekLabel(w.week_start, w.partial) };
    if (w.wellness_index !== null) row.index = w.wellness_index;
    return row;
  });
}

// ---- trends page ----------------------------------------------------------------------------

function WeeklyIndex({ data }: { data: WellnessAnalytics }) {
  const enough = data.weeks.some((w) => w.wellness_index !== null);
  return (
    <SectionCard
      title="Wellness over time"
      description={`Your last ${data.weeks.length} weeks, built from the mood, stress and sleep you reported.`}
    >
      {enough ? (
        <div className="space-y-4">
          <TrendChart
            title={`Weekly wellness index, last ${data.weeks.length} weeks`}
            data={indexRows(data.weeks)}
            xKey="week"
            yDomain={[0, 100]}
            series={[{ key: "index", label: "Wellness index (0 to 100)" }]}
          />
          <p className="text-sm text-muted-foreground">
            The index combines your mood, stress (less stress counts higher) and sleep quality. It
            only describes what you reported. Weeks with fewer than two of those are left out.
          </p>
        </div>
      ) : (
        <div className="space-y-3">
          <p className="font-medium">Not enough data yet</p>
          <p className="text-sm text-muted-foreground">
            A week appears here once you have logged at least two of mood, stress and sleep quality
            in it.
          </p>
          <Button asChild variant="outline" size="sm">
            <Link href="/student/check-in">Do a check-in</Link>
          </Button>
        </div>
      )}
    </SectionCard>
  );
}

function WellbeingChecks({ data }: { data: WellnessAnalytics }) {
  const checks = data.wellbeing_checks;
  const latest = checks.at(-1);
  return (
    <SectionCard
      title="Wellbeing checks"
      description="Your results from the two-minute wellbeing check. Only you can see these."
    >
      {checks.length >= 2 ? (
        <TrendChart
          title="Wellbeing check results, most recent checks"
          data={checks.map((c) => ({ check: formatShortDate(c.completed_at), percent: c.percent }))}
          xKey="check"
          yDomain={[0, 100]}
          series={[{ key: "percent", label: "Result (%)" }]}
        />
      ) : (
        <div className="space-y-3">
          <p className="font-medium">
            {latest
              ? `One check so far: ${latest.percent}% · ${latest.band.label}`
              : "No checks yet"}
          </p>
          <p className="text-sm text-muted-foreground">
            {latest
              ? "Take another in a couple of weeks to see how it moves."
              : "Take the check to start your own record. It takes about two minutes."}
          </p>
          <Button asChild variant="outline" size="sm">
            <Link href="/student/assessment">
              <ClipboardCheck aria-hidden="true" />
              {latest ? "Take another check" : "Take the check"}
            </Link>
          </Button>
        </div>
      )}
    </SectionCard>
  );
}

/** The weekly wellness index and the wellbeing-check history, for the Trends page. */
export function WellnessOverTime({ query }: { query: QueryResult<WellnessAnalytics> }) {
  return (
    <DataView query={query} skeleton={loading("Loading your weekly picture…")}>
      {(data) => (
        <>
          <WeeklyIndex data={data} />
          <WellbeingChecks data={data} />
          <p className="text-sm text-muted-foreground">{data.disclaimer}</p>
        </>
      )}
    </DataView>
  );
}

// ---- goals page -----------------------------------------------------------------------------

/** Goal counts, average progress and goals finished each week, for the Goals page. */
export function GoalProgress({ query }: { query: QueryResult<WellnessAnalytics> }) {
  return (
    <DataView query={query} skeleton={loading("Loading your goal figures…")}>
      {({ goals, weeks }) => {
        if (goals.active + goals.completed + goals.other === 0) return null;
        const average = goals.average_progress_percent;
        const finished = goals.completed_by_week.reduce((sum, w) => sum + w.completed, 0);
        const last = goals.completed_by_week.length - 1;
        return (
          <SectionCard
            title="Goal progress"
            description="Where your goals stand today, and the ones you have finished lately."
          >
            <div className="space-y-6">
              <div className="grid gap-4 sm:grid-cols-3">
                <StatCard label="Active goals" value={goals.active} icon={Target} />
                <StatCard label="Completed goals" value={goals.completed} icon={ListChecks} />
                <StatCard
                  label="Average progress"
                  value={average === null ? "—" : `${Math.round(average)}%`}
                  hint={
                    average === null ? "Add a target number to see this" : "Across active goals"
                  }
                  icon={TrendingUp}
                />
              </div>

              {goals.by_category.length > 0 && (
                <div className="space-y-2">
                  <h3 className="text-sm font-medium">By area</h3>
                  <ul className="divide-y rounded-lg border">
                    {goals.by_category.map((c) => (
                      <li
                        key={c.category}
                        className="flex flex-wrap items-center justify-between gap-2 px-3 py-2 text-sm"
                      >
                        <span className="font-medium">
                          {GOAL_CATEGORY_LABELS[c.category] ?? c.category}
                        </span>
                        <span className="text-muted-foreground">
                          {c.active} active · {c.completed} completed
                          {c.average_progress_percent === null
                            ? ""
                            : ` · ${Math.round(c.average_progress_percent)}% average progress`}
                        </span>
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              {finished > 0 ? (
                <BarSeriesChart
                  title={`Goals completed each week, last ${weeks.length} weeks`}
                  data={goals.completed_by_week.map((w, i) => ({
                    week: weekLabel(w.week_start, i === last),
                    completed: w.completed,
                  }))}
                  xKey="week"
                  series={[{ key: "completed", label: "Goals completed" }]}
                />
              ) : (
                <p className="text-sm text-muted-foreground">
                  No goals finished in the last {weeks.length} weeks yet. Small steps still count.
                </p>
              )}
              <p className="text-sm text-muted-foreground">
                Progress shows where each goal stands now, not how it changed over time.
              </p>
            </div>
          </SectionCard>
        );
      }}
    </DataView>
  );
}
