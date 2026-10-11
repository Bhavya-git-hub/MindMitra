"use client";

import { ClipboardCheck, HeartPulse, MoonStar, Smile, Waves } from "lucide-react";
import Link from "next/link";
import * as React from "react";

import { SectionCard } from "@/components/cards/section-card";
import { BarSeriesChart, TrendChart } from "@/components/charts";
import { PageHeader } from "@/components/layout/page-header";
import { EmptyState } from "@/components/states/empty-state";
import { InlineAlert } from "@/components/states/inline-alert";
import { WellnessOverTime, useWellnessAnalytics } from "@/components/student/analytics-sections";
import { DataView } from "@/components/student/data-view";
import { SaveButton, useSubmit } from "@/components/student/form-bits";
import { MetricCard } from "@/components/student/metric-card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import type { AssessmentSnapshot, Instrument } from "@/lib/api/student-schemas";
import { formatDateTime, formatDuration } from "@/lib/format";
import { useQuery } from "@/lib/hooks/use-query";
import { useStudentApi } from "@/lib/hooks/use-student-api";
import { notify } from "@/lib/toast";
import { averageOf, chartRows, hasAny } from "@/lib/trend-data";
import { cn } from "@/lib/utils";

const score = (value: number | null) => (value === null ? null : `${value.toFixed(1)} / 5`);

// ---- wellness assessment -----------------------------------------------------------------------

function AssessmentResult({ result }: { result: AssessmentSnapshot }) {
  return (
    <SectionCard
      title="Your result"
      description={`Completed ${formatDateTime(result.completed_at)}`}
    >
      <div role="status" className="space-y-3">
        <p className="text-3xl font-semibold">
          {result.percent}% <span className="text-base font-normal">· {result.band.label}</span>
        </p>
        <p>{result.band.message}</p>
        <p className="text-sm text-muted-foreground">
          This is a snapshot of how you have felt, not a diagnosis. If something feels heavy,
          talking to someone can help.
        </p>
        <div className="flex flex-wrap gap-2">
          <Button asChild>
            <Link href="/student/therapists">Find a therapist</Link>
          </Button>
          <Button asChild variant="outline">
            <Link href="/student/recommendations">See suggestions</Link>
          </Button>
        </div>
      </div>
    </SectionCard>
  );
}

function AssessmentForm({
  instrument,
  onDone,
}: {
  instrument: Instrument;
  onDone: (result: AssessmentSnapshot) => void;
}) {
  const api = useStudentApi();
  const [answers, setAnswers] = React.useState<Record<string, number>>({});
  const [missing, setMissing] = React.useState(false);
  const { pending, error, run } = useSubmit();

  function submit(event: React.FormEvent) {
    event.preventDefault();
    if (instrument.questions.some((q) => answers[q.key] === undefined)) {
      setMissing(true);
      return;
    }
    void run(async () => {
      const result = await api.submitAssessment(answers);
      notify.success("Check saved");
      onDone(result);
    });
  }

  return (
    <form onSubmit={submit} noValidate className="space-y-6">
      <p>{instrument.intro}</p>
      {instrument.questions.map((q, index) => (
        <fieldset key={q.key} className="space-y-2">
          <legend className="font-medium">
            {index + 1}. {q.text}
          </legend>
          <div className="grid gap-2 sm:grid-cols-3 lg:grid-cols-6">
            {instrument.options.map((o) => {
              const id = `${q.key}-${o.value}`;
              const checked = answers[q.key] === o.value;
              return (
                <div key={o.value}>
                  <input
                    id={id}
                    type="radio"
                    name={q.key}
                    value={o.value}
                    checked={checked}
                    onChange={() => {
                      setAnswers((a) => ({ ...a, [q.key]: o.value }));
                      setMissing(false);
                    }}
                    className="peer sr-only"
                  />
                  <label
                    htmlFor={id}
                    className={cn(
                      "flex min-h-11 cursor-pointer items-center justify-center rounded-lg border bg-card px-2 py-2 text-center text-sm",
                      "peer-focus-visible:ring-[3px] peer-focus-visible:ring-ring/50 hover:bg-accent",
                      "peer-checked:border-primary peer-checked:bg-primary peer-checked:text-primary-foreground",
                    )}
                  >
                    {o.label}
                  </label>
                </div>
              );
            })}
          </div>
        </fieldset>
      ))}
      {missing && (
        <InlineAlert tone="warning">Please answer every question to see your result.</InlineAlert>
      )}
      {error && <InlineAlert tone="destructive">{error}</InlineAlert>}
      <p className="text-sm text-muted-foreground">{instrument.disclaimer}</p>
      <SaveButton pending={pending}>See my result</SaveButton>
    </form>
  );
}

export function AssessmentView() {
  const api = useStudentApi();
  const instrument = useQuery("assessment-instrument", () => api.assessmentInstrument());
  const history = useQuery("assessment-history", () => api.assessments());
  const [result, setResult] = React.useState<AssessmentSnapshot | null>(null);

  return (
    <>
      <PageHeader
        title="Wellbeing check"
        description="Five quick questions about the last two weeks. It takes about two minutes."
      />
      {result ? (
        <AssessmentResult result={result} />
      ) : (
        <DataView query={instrument}>
          {(i) => (
            <SectionCard title={i.title} description={i.attribution}>
              <AssessmentForm
                instrument={i}
                onDone={(r) => {
                  setResult(r);
                  void history.reload();
                }}
              />
            </SectionCard>
          )}
        </DataView>
      )}
      <SectionCard title="Previous checks" description="Only you can see these.">
        <DataView
          query={history}
          skeleton={<p className="text-sm text-muted-foreground">Loading…</p>}
        >
          {(rows) =>
            rows.length === 0 ? (
              <p className="text-sm text-muted-foreground">You haven&apos;t taken a check yet.</p>
            ) : (
              <ul className="divide-y">
                {rows.map((r) => (
                  <li key={r.id} className="flex flex-wrap items-center justify-between gap-2 py-3">
                    <span>
                      <span className="font-medium">{r.percent}%</span> · {r.band.label}
                    </span>
                    <span className="text-sm text-muted-foreground">
                      {formatDateTime(r.completed_at)}
                    </span>
                  </li>
                ))}
              </ul>
            )
          }
        </DataView>
      </SectionCard>
    </>
  );
}

// ---- wellness dashboard ------------------------------------------------------------------------

const TRACKERS = [
  { href: "/student/mood", label: "Mood", icon: Smile },
  { href: "/student/stress", label: "Stress", icon: Waves },
  { href: "/student/sleep", label: "Sleep", icon: MoonStar },
  { href: "/student/assessment", label: "Wellbeing check", icon: ClipboardCheck },
] as const;

export function WellnessView() {
  const api = useStudentApi();
  const summary = useQuery("wellness-summary", () => api.summary());
  const trends = useQuery("trends-30", () => api.trends(30));

  return (
    <>
      <PageHeader
        title="Wellness"
        description="Your mood, stress and sleep together, in plain words."
      />
      <DataView query={summary}>
        {(s) => {
          const sleepMinutes = s.sleep.last_night_minutes ?? s.sleep.average_minutes_7d;
          return (
            <>
              <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
                <MetricCard
                  label="Mood"
                  icon={Smile}
                  value={score(s.mood.today ?? s.mood.average_7d)}
                  indicator={s.mood.indicator?.label}
                  direction={s.mood.direction}
                  empty="No check-in yet"
                />
                <MetricCard
                  label="Stress"
                  icon={Waves}
                  value={score(s.stress.today ?? s.stress.average_7d)}
                  indicator={s.stress.indicator?.label}
                  direction={s.stress.direction}
                  empty="Not logged yet"
                />
                <MetricCard
                  label="Sleep"
                  icon={MoonStar}
                  value={sleepMinutes === null ? null : formatDuration(Math.round(sleepMinutes))}
                  indicator={s.sleep.indicator?.label}
                  direction={s.sleep.direction}
                  empty="Not logged yet"
                />
                <MetricCard
                  label="Wellbeing check"
                  icon={HeartPulse}
                  value={s.wellbeing ? `${s.wellbeing.percent}%` : null}
                  indicator={s.wellbeing?.band.label}
                  empty="Take the 2-minute check"
                />
              </div>
              <p className="text-sm text-muted-foreground">{s.disclaimer}</p>

              <SectionCard
                title="This week at a glance"
                description={`${s.check_in.check_ins_last_7d} check-in${
                  s.check_in.check_ins_last_7d === 1 ? "" : "s"
                } in the last 7 days${
                  s.check_in.streak_days > 1 ? ` · ${s.check_in.streak_days} days in a row` : ""
                }.`}
              >
                <div className="flex flex-wrap gap-2">
                  {s.check_in.emotions_today.length > 0 ? (
                    s.check_in.emotions_today.map((e) => (
                      <Badge key={e} variant="info" className="capitalize">
                        {e}
                      </Badge>
                    ))
                  ) : (
                    <p className="text-sm text-muted-foreground">
                      No feelings logged today.{" "}
                      <Link href="/student/check-in" className="underline underline-offset-4">
                        Check in
                      </Link>
                    </p>
                  )}
                </div>
              </SectionCard>
            </>
          );
        }}
      </DataView>

      <DataView query={trends} skeleton={null}>
        {(t) =>
          hasAny(t.points, "mood") || hasAny(t.points, "stress") ? (
            <SectionCard
              title="Last 30 days"
              footer={
                <Button asChild variant="ghost" size="sm">
                  <Link href="/student/trends">More detail</Link>
                </Button>
              }
            >
              <TrendChart
                title="Mood and stress, last 30 days"
                data={chartRows(t.points, ["mood", "stress"])}
                xKey="day"
                yDomain={[1, 5]}
                series={[
                  ...(hasAny(t.points, "mood") ? [{ key: "mood", label: "Mood (5 is best)" }] : []),
                  ...(hasAny(t.points, "stress")
                    ? [{ key: "stress", label: "Stress (5 is highest)" }]
                    : []),
                ]}
              />
            </SectionCard>
          ) : null
        }
      </DataView>

      <SectionCard title="Log something" description="Add to your picture whenever it suits you.">
        <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {TRACKERS.map(({ href, label, icon: Icon }) => (
            <li key={href}>
              <Button asChild variant="outline" className="h-auto w-full justify-start py-3">
                <Link href={href}>
                  <Icon aria-hidden="true" />
                  {label}
                </Link>
              </Button>
            </li>
          ))}
        </ul>
      </SectionCard>
    </>
  );
}

// ---- personal trends ----------------------------------------------------------------------------

const RANGES = [7, 30, 90] as const;

export function TrendsView() {
  const api = useStudentApi();
  const [days, setDays] = React.useState<(typeof RANGES)[number]>(30);
  const trends = useQuery(`trends-${days}`, () => api.trends(days));
  const analytics = useWellnessAnalytics();

  return (
    <>
      <PageHeader
        title="Your trends"
        description="Patterns over time. Gaps just mean nothing was logged that day."
      />
      <div role="group" aria-label="Time range" className="flex flex-wrap gap-2">
        {RANGES.map((r) => (
          <Button
            key={r}
            type="button"
            size="sm"
            variant={days === r ? "default" : "outline"}
            aria-pressed={days === r}
            onClick={() => setDays(r)}
          >
            {r} days
          </Button>
        ))}
      </div>
      <DataView query={trends}>
        {(t) => {
          const mood = averageOf(t.points, "mood");
          const stress = averageOf(t.points, "stress");
          const sleep = averageOf(t.points, "sleep_hours");
          const nothing = !t.points.some(
            (p) => p.mood !== null || p.stress !== null || p.sleep_minutes !== null,
          );
          if (nothing) {
            return (
              <EmptyState
                icon={HeartPulse}
                title="Nothing to chart yet"
                description="Your trends appear after a few check-ins."
                action={
                  <Button asChild>
                    <Link href="/student/check-in">Do a check-in</Link>
                  </Button>
                }
              />
            );
          }
          return (
            <>
              <div className="grid gap-4 sm:grid-cols-3">
                <MetricCard
                  label="Average mood"
                  icon={Smile}
                  value={mood === null ? null : `${mood.toFixed(1)} / 5`}
                  empty="Not logged"
                />
                <MetricCard
                  label="Average stress"
                  icon={Waves}
                  value={stress === null ? null : `${stress.toFixed(1)} / 5`}
                  empty="Not logged"
                />
                <MetricCard
                  label="Average sleep"
                  icon={MoonStar}
                  value={sleep === null ? null : formatDuration(Math.round(sleep * 60))}
                  empty="Not logged"
                />
              </div>
              {hasAny(t.points, "mood") && (
                <SectionCard title="Mood and energy">
                  <TrendChart
                    title={`Mood and energy, last ${days} days`}
                    data={chartRows(t.points, ["mood", "energy"])}
                    xKey="day"
                    yDomain={[1, 5]}
                    series={[
                      { key: "mood", label: "Mood (5 is best)" },
                      ...(hasAny(t.points, "energy") ? [{ key: "energy", label: "Energy" }] : []),
                    ]}
                  />
                </SectionCard>
              )}
              {hasAny(t.points, "stress") && (
                <SectionCard title="Stress">
                  <TrendChart
                    title={`Stress, last ${days} days`}
                    data={chartRows(t.points, ["stress"])}
                    xKey="day"
                    yDomain={[1, 5]}
                    series={[{ key: "stress", label: "Stress (5 is highest)" }]}
                  />
                </SectionCard>
              )}
              {hasAny(t.points, "sleep_hours") && (
                <SectionCard title="Sleep">
                  <BarSeriesChart
                    title={`Hours of sleep, last ${days} days`}
                    data={chartRows(t.points, ["sleep_hours"])}
                    xKey="day"
                    series={[{ key: "sleep_hours", label: "Hours slept" }]}
                  />
                </SectionCard>
              )}
              <p className="text-sm text-muted-foreground">{t.disclaimer}</p>
            </>
          );
        }}
      </DataView>
      <WellnessOverTime query={analytics} />
    </>
  );
}
