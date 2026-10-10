"use client";

import { HeartPulse, Lightbulb, Lock } from "lucide-react";
import * as React from "react";

import { BarSeriesChart, TrendChart } from "@/components/charts";
import { SectionCard } from "@/components/cards/section-card";
import { StatCard } from "@/components/cards/stat-card";
import { EmptyState } from "@/components/states/empty-state";
import { InlineAlert } from "@/components/states/inline-alert";
import { DataView } from "@/components/student/data-view";
import { SaveButton, useSubmit } from "@/components/student/form-bits";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { formatDuration, formatShortDate, titleCase } from "@/lib/format";
import { useQuery } from "@/lib/hooks/use-query";
import { useTherapistApi } from "@/lib/hooks/use-therapist-api";
import { averageOf, chartRows, hasAny } from "@/lib/trend-data";
import { notify } from "@/lib/toast";

import { FollowUpRow, NewFollowUpForm } from "./follow-ups-view";
import { SegmentedTabs } from "./shared";

const RANGES = [
  { value: "7", label: "7 days" },
  { value: "30", label: "30 days" },
  { value: "90", label: "90 days" },
] as const;

function NotShared({ what, name }: { what: string; name: string }) {
  return (
    <EmptyState
      icon={Lock}
      title={`${name} hasn't shared ${what}`}
      description="That's their choice and it can change at any time. Nothing is hidden from you by mistake."
    />
  );
}

export function TrendsPanel({ studentId, name }: { studentId: string; name: string }) {
  const api = useTherapistApi();
  const [range, setRange] = React.useState<(typeof RANGES)[number]["value"]>("30");
  const days = Number(range);
  const trends = useQuery(`t-trends-${studentId}-${days}`, () =>
    api.studentTrends(studentId, days),
  );

  return (
    <SectionCard
      title="Check-in trends"
      description={`What ${name} reported in their daily check-ins.`}
      action={
        <SegmentedTabs
          label="Time range"
          value={range}
          options={RANGES.map((r) => ({ value: r.value, label: r.label }))}
          onChange={setRange}
        />
      }
    >
      <DataView query={trends}>
        {(t) => {
          const mood = averageOf(t.points, "mood");
          const stress = averageOf(t.points, "stress");
          const sleep = averageOf(t.points, "sleep_hours");
          if (
            !t.points.some((p) => p.mood !== null || p.stress !== null || p.sleep_minutes !== null)
          ) {
            return (
              <EmptyState
                icon={HeartPulse}
                title="No check-ins in this period"
                description="Trends appear once they have checked in a few times."
              />
            );
          }
          return (
            <div className="space-y-6">
              <div className="grid gap-4 sm:grid-cols-3">
                <StatCard
                  label="Average mood"
                  value={mood === null ? "—" : `${mood.toFixed(1)} / 5`}
                  hint="5 is best"
                />
                <StatCard
                  label="Average stress"
                  value={stress === null ? "—" : `${stress.toFixed(1)} / 5`}
                  hint="5 is highest"
                />
                <StatCard
                  label="Average sleep"
                  value={sleep === null ? "—" : formatDuration(Math.round(sleep * 60))}
                />
              </div>
              {hasAny(t.points, "mood") && (
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
              )}
              {hasAny(t.points, "stress") && (
                <TrendChart
                  title={`Stress, last ${days} days`}
                  data={chartRows(t.points, ["stress"])}
                  xKey="day"
                  yDomain={[1, 5]}
                  series={[{ key: "stress", label: "Stress (5 is highest)" }]}
                />
              )}
              {hasAny(t.points, "sleep_hours") && (
                <BarSeriesChart
                  title={`Hours of sleep, last ${days} days`}
                  data={chartRows(t.points, ["sleep_hours"])}
                  xKey="day"
                  series={[{ key: "sleep_hours", label: "Hours slept" }]}
                />
              )}
              <p className="text-sm text-muted-foreground">{t.disclaimer}</p>
            </div>
          );
        }}
      </DataView>
    </SectionCard>
  );
}

export function AssessmentsPanel({ studentId }: { studentId: string }) {
  const api = useTherapistApi();
  const rows = useQuery(`t-assessments-${studentId}`, () => api.studentAssessments(studentId));
  return (
    <SectionCard
      title="Wellbeing checks"
      description="Scores from the short wellbeing questionnaire. A score describes what they reported that day; it is not a diagnosis."
    >
      <DataView query={rows}>
        {(list) =>
          list.length === 0 ? (
            <p className="text-sm text-muted-foreground">No wellbeing checks taken yet.</p>
          ) : (
            <ul className="divide-y">
              {list.map((a) => (
                <li key={a.id} className="flex items-center justify-between gap-3 py-3">
                  <span>{formatShortDate(a.completed_at)}</span>
                  <Badge variant="secondary">
                    {a.score} / {a.max_score}
                  </Badge>
                </li>
              ))}
            </ul>
          )
        }
      </DataView>
    </SectionCard>
  );
}

export function RecommendationsPanel({ studentId, name }: { studentId: string; name: string }) {
  const api = useTherapistApi();
  const made = useQuery(`t-recs-${studentId}`, () => api.studentRecommendations(studentId));
  const [title, setTitle] = React.useState("");
  const [why, setWhy] = React.useState("");
  const [formError, setFormError] = React.useState<string>();
  const { pending, error, run } = useSubmit();

  function submit(event: React.FormEvent) {
    event.preventDefault();
    if (title.trim().length < 3 || why.trim().length < 3) {
      setFormError("Add a short title and a kind reason.");
      return;
    }
    setFormError(undefined);
    void run(async () => {
      await api.recommend(studentId, { title: title.trim(), rationale: why.trim() });
      notify.success("Suggestion sent", `${name} sees it under Suggestions, marked as from you.`);
      setTitle("");
      setWhy("");
      await made.reload();
    }, "We couldn't send that. You can have up to 5 open suggestions per student.");
  }

  return (
    <SectionCard
      title="Suggestions from you"
      description="Gentle, optional ideas. The student sees them as coming from you."
    >
      <div className="space-y-6">
        <form onSubmit={submit} className="space-y-4" noValidate>
          <div className="space-y-2">
            <Label htmlFor="rec-title">Suggestion</Label>
            <Input
              id="rec-title"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              maxLength={200}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="rec-why">Why you&apos;re suggesting it</Label>
            <Textarea
              id="rec-why"
              value={why}
              onChange={(e) => setWhy(e.target.value)}
              maxLength={600}
              rows={3}
            />
          </div>
          {formError && (
            <p role="alert" className="text-sm text-destructive">
              {formError}
            </p>
          )}
          {error && <InlineAlert tone="destructive">{error}</InlineAlert>}
          <SaveButton pending={pending}>Send suggestion</SaveButton>
        </form>
        <DataView query={made} skeleton={null}>
          {(list) =>
            list.length === 0 ? null : (
              <ul className="divide-y rounded-lg border">
                {list.map((r) => (
                  <li key={r.id} className="space-y-1 px-4 py-3">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <p className="flex items-center gap-2 font-medium">
                        <Lightbulb className="size-4" aria-hidden="true" />
                        {r.title}
                      </p>
                      <Badge variant={r.status === "completed" ? "success" : "outline"}>
                        {r.status === "pending" ? "Not seen yet" : titleCase(r.status)}
                      </Badge>
                    </div>
                    <p className="text-sm text-muted-foreground">{r.rationale}</p>
                  </li>
                ))}
              </ul>
            )
          }
        </DataView>
      </div>
    </SectionCard>
  );
}

export function StudentFollowUps({ studentId }: { studentId: string }) {
  const api = useTherapistApi();
  const rows = useQuery(`t-student-follow-ups-${studentId}`, () =>
    api.followUps("open", studentId),
  );
  return (
    <SectionCard title="Follow-ups" description="Private reminders about this student.">
      <div className="space-y-5">
        <DataView query={rows} skeleton={null}>
          {(list) =>
            list.length === 0 ? (
              <p className="text-sm text-muted-foreground">Nothing open.</p>
            ) : (
              <ul className="divide-y">
                {list.map((f) => (
                  <FollowUpRow key={f.id} f={f} onChanged={rows.reload} showStudent={false} />
                ))}
              </ul>
            )
          }
        </DataView>
        <NewFollowUpForm studentId={studentId} onCreated={rows.reload} />
      </div>
    </SectionCard>
  );
}

export { NotShared };
