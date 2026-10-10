"use client";

import * as React from "react";

import { SectionCard } from "@/components/cards/section-card";
import { BarSeriesChart, TrendChart } from "@/components/charts";
import { PageHeader } from "@/components/layout/page-header";
import { EmptyState } from "@/components/states/empty-state";
import { InlineAlert } from "@/components/states/inline-alert";
import { ChipGroup } from "@/components/student/chip-group";
import { DataView } from "@/components/student/data-view";
import { SaveButton, useSubmit } from "@/components/student/form-bits";
import { RatingScale } from "@/components/student/rating-scale";
import { SupportCallout } from "@/components/student/support-callout";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import type { SupportInfo } from "@/lib/api/student-schemas";
import { notify } from "@/lib/toast";
import { formatDateTime, formatDuration, formatShortDate } from "@/lib/format";
import { useQuery } from "@/lib/hooks/use-query";
import { useStudentApi } from "@/lib/hooks/use-student-api";
import { sleepWindow } from "@/lib/sleep";
import {
  EMOTIONS,
  ENERGY_LABELS,
  MOOD_LABELS,
  SLEEP_QUALITY_LABELS,
  STRESSORS,
  STRESS_LABELS,
} from "@/lib/student-options";
import { averageOf, chartRows, hasAny } from "@/lib/trend-data";

const WINDOW_DAYS = 30;

// ---- mood -----------------------------------------------------------------------------------

export function MoodView() {
  const api = useStudentApi();
  const entries = useQuery("mood-entries", () => api.moodEntries(WINDOW_DAYS));
  const trends = useQuery(`trends-${WINDOW_DAYS}`, () => api.trends(WINDOW_DAYS));
  const [mood, setMood] = React.useState<number>();
  const [energy, setEnergy] = React.useState<number>();
  const [emotions, setEmotions] = React.useState<string[]>([]);
  const [note, setNote] = React.useState("");
  const [moodError, setMoodError] = React.useState<string>();
  const [support, setSupport] = React.useState<SupportInfo | null>(null);
  const { pending, error, run } = useSubmit();

  function submit(event: React.FormEvent) {
    event.preventDefault();
    if (mood === undefined) {
      setMoodError("Choose a mood to log.");
      return;
    }
    void run(async () => {
      const result = await api.checkIn({
        mood_score: mood,
        energy_level: energy,
        emotions,
        note: note.trim() || undefined,
      });
      setSupport(result.support);
      setMood(undefined);
      setEnergy(undefined);
      setEmotions([]);
      setNote("");
      notify.success("Mood logged");
      await Promise.all([entries.reload(), trends.reload()]);
    });
  }

  return (
    <>
      <PageHeader
        title="Mood"
        description="Log how you feel whenever you like. Patterns show up over time."
      />
      {support && <SupportCallout message={support.message} />}
      <SectionCard title="Log your mood">
        <form onSubmit={submit} noValidate className="space-y-6">
          <RatingScale
            legend="How are you feeling?"
            labels={MOOD_LABELS}
            value={mood}
            onChange={(v) => {
              setMood(v);
              setMoodError(undefined);
            }}
            error={moodError}
          />
          <ChipGroup
            legend="Which words fit? (optional)"
            options={EMOTIONS}
            value={emotions}
            onChange={setEmotions}
          />
          <RatingScale
            legend="Energy (optional)"
            labels={ENERGY_LABELS}
            value={energy}
            onChange={setEnergy}
            optional
          />
          <div className="space-y-2">
            <Label htmlFor="mood-note">Private note (optional)</Label>
            <Textarea
              id="mood-note"
              value={note}
              onChange={(e) => setNote(e.target.value)}
              maxLength={2000}
              rows={3}
            />
          </div>
          {error && <InlineAlert tone="destructive">{error}</InlineAlert>}
          <SaveButton pending={pending}>Log mood</SaveButton>
        </form>
      </SectionCard>

      <DataView query={trends} skeleton={null}>
        {(t) => {
          const avg = averageOf(t.points, "mood");
          return hasAny(t.points, "mood") ? (
            <SectionCard
              title={`Last ${WINDOW_DAYS} days`}
              description={
                avg === null
                  ? undefined
                  : `Average mood: ${avg.toFixed(1)} out of 5. Higher is better.`
              }
            >
              <TrendChart
                title="Mood by day"
                data={chartRows(t.points, ["mood", "energy"])}
                xKey="day"
                yDomain={[1, 5]}
                series={[
                  { key: "mood", label: "Mood" },
                  ...(hasAny(t.points, "energy") ? [{ key: "energy", label: "Energy" }] : []),
                ]}
              />
            </SectionCard>
          ) : null;
        }}
      </DataView>

      <SectionCard
        title="Recent entries"
        description="Newest first. Notes are only ever visible to you."
      >
        <DataView
          query={entries}
          skeleton={<p className="text-sm text-muted-foreground">Loading…</p>}
        >
          {(rows) =>
            rows.length === 0 ? (
              <EmptyState
                title="No entries yet"
                description="Your first mood log will appear here."
              />
            ) : (
              <ul className="divide-y">
                {rows.map((r) => (
                  <li key={r.id} className="space-y-1 py-3">
                    <p className="flex flex-wrap items-center gap-2">
                      <span className="font-medium">
                        {r.mood_score} of 5, {MOOD_LABELS[r.mood_score]}
                      </span>
                      <span className="text-sm text-muted-foreground">
                        {formatDateTime(r.logged_at)}
                      </span>
                    </p>
                    {r.emotions.length > 0 && (
                      <p className="flex flex-wrap gap-1.5">
                        {r.emotions.map((e) => (
                          <Badge key={e}>{e}</Badge>
                        ))}
                      </p>
                    )}
                    {r.note && <p className="text-sm text-muted-foreground">{r.note}</p>}
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

// ---- stress ---------------------------------------------------------------------------------

export function StressView() {
  const api = useStudentApi();
  const entries = useQuery("stress-entries", () => api.stressEntries(WINDOW_DAYS));
  const trends = useQuery(`trends-${WINDOW_DAYS}`, () => api.trends(WINDOW_DAYS));
  const [level, setLevel] = React.useState<number>();
  const [stressors, setStressors] = React.useState<string[]>([]);
  const [levelError, setLevelError] = React.useState<string>();
  const { pending, error, run } = useSubmit();

  function submit(event: React.FormEvent) {
    event.preventDefault();
    if (level === undefined) {
      setLevelError("Choose a stress level to log.");
      return;
    }
    void run(async () => {
      await api.logStress(level, stressors);
      setLevel(undefined);
      setStressors([]);
      notify.success("Stress logged");
      await Promise.all([entries.reload(), trends.reload()]);
    });
  }

  return (
    <>
      <PageHeader
        title="Stress"
        description="Some stress is normal. Logging it helps you see what lifts it and what doesn't."
      />
      <SectionCard title="Log your stress">
        <form onSubmit={submit} noValidate className="space-y-6">
          <RatingScale
            legend="How stressed do you feel right now?"
            labels={STRESS_LABELS}
            value={level}
            onChange={(v) => {
              setLevel(v);
              setLevelError(undefined);
            }}
            error={levelError}
          />
          <ChipGroup
            legend="What's contributing? (optional)"
            options={STRESSORS}
            value={stressors}
            onChange={setStressors}
          />
          {error && <InlineAlert tone="destructive">{error}</InlineAlert>}
          <SaveButton pending={pending}>Log stress</SaveButton>
        </form>
      </SectionCard>

      <DataView query={trends} skeleton={null}>
        {(t) =>
          hasAny(t.points, "stress") ? (
            <SectionCard
              title={`Last ${WINDOW_DAYS} days`}
              description="1 is very calm and 5 is very stressed."
            >
              <TrendChart
                title="Stress by day"
                data={chartRows(t.points, ["stress"])}
                xKey="day"
                yDomain={[1, 5]}
                series={[{ key: "stress", label: "Stress" }]}
              />
            </SectionCard>
          ) : null
        }
      </DataView>

      <SectionCard title="Recent entries">
        <DataView
          query={entries}
          skeleton={<p className="text-sm text-muted-foreground">Loading…</p>}
        >
          {(rows) =>
            rows.length === 0 ? (
              <EmptyState
                title="No entries yet"
                description="Your first stress log will appear here."
              />
            ) : (
              <ul className="divide-y">
                {rows.map((r) => (
                  <li key={r.id} className="space-y-1 py-3">
                    <p className="flex flex-wrap items-center gap-2">
                      <span className="font-medium">
                        {r.stress_level} of 5, {STRESS_LABELS[r.stress_level]}
                      </span>
                      <span className="text-sm text-muted-foreground">
                        {formatDateTime(r.logged_at)}
                      </span>
                    </p>
                    {r.stressors.length > 0 && (
                      <p className="flex flex-wrap gap-1.5">
                        {r.stressors.map((s) => (
                          <Badge key={s}>{s}</Badge>
                        ))}
                      </p>
                    )}
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

// ---- sleep ----------------------------------------------------------------------------------

export function SleepView() {
  const api = useStudentApi();
  const entries = useQuery("sleep-entries", () => api.sleepEntries(WINDOW_DAYS));
  const trends = useQuery(`trends-${WINDOW_DAYS}`, () => api.trends(WINDOW_DAYS));
  const [bed, setBed] = React.useState("23:00");
  const [wake, setWake] = React.useState("07:00");
  const [quality, setQuality] = React.useState<number>();
  const [qualityError, setQualityError] = React.useState<string>();
  const { pending, error, run } = useSubmit();
  const times = sleepWindow(bed, wake);

  function submit(event: React.FormEvent) {
    event.preventDefault();
    if (quality === undefined) {
      setQualityError("Tell us how well you slept.");
      return;
    }
    if (!times) return;
    void run(async () => {
      await api.logSleep({ bedtime: times.bedtime, wake_time: times.wake_time, quality });
      setQuality(undefined);
      notify.success("Sleep logged", "Logging again for the same morning replaces it.");
      await Promise.all([entries.reload(), trends.reload()]);
    });
  }

  return (
    <>
      <PageHeader
        title="Sleep"
        description="Log last night's sleep. One entry per morning, and you can correct it any time."
      />
      <SectionCard title="Log last night">
        <form onSubmit={submit} noValidate className="space-y-6">
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-2">
              <Label htmlFor="sleep-bed">I went to bed at</Label>
              <Input
                id="sleep-bed"
                type="time"
                value={bed}
                onChange={(e) => setBed(e.target.value)}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="sleep-wake">I woke up at</Label>
              <Input
                id="sleep-wake"
                type="time"
                value={wake}
                onChange={(e) => setWake(e.target.value)}
              />
            </div>
          </div>
          {times && (
            <p className="text-sm text-muted-foreground" aria-live="polite">
              That&apos;s about {formatDuration(times.durationMinutes)} of sleep.
            </p>
          )}
          <RatingScale
            legend="How well did you sleep?"
            labels={SLEEP_QUALITY_LABELS}
            value={quality}
            onChange={(v) => {
              setQuality(v);
              setQualityError(undefined);
            }}
            error={qualityError}
          />
          {error && <InlineAlert tone="destructive">{error}</InlineAlert>}
          <SaveButton pending={pending}>Log sleep</SaveButton>
        </form>
      </SectionCard>

      <DataView query={trends} skeleton={null}>
        {(t) =>
          hasAny(t.points, "sleep_hours") ? (
            <SectionCard
              title={`Last ${WINDOW_DAYS} days`}
              description={`Average: ${formatDuration(Math.round((averageOf(t.points, "sleep_hours") ?? 0) * 60))} a night.`}
            >
              <BarSeriesChart
                title="Hours of sleep by night"
                data={chartRows(t.points, ["sleep_hours"])}
                xKey="day"
                series={[{ key: "sleep_hours", label: "Hours slept" }]}
              />
            </SectionCard>
          ) : null
        }
      </DataView>

      <SectionCard title="Recent nights">
        <DataView
          query={entries}
          skeleton={<p className="text-sm text-muted-foreground">Loading…</p>}
        >
          {(rows) =>
            rows.length === 0 ? (
              <EmptyState
                title="No nights logged yet"
                description="Your first sleep log will appear here."
              />
            ) : (
              <ul className="divide-y">
                {rows.map((r) => (
                  <li key={r.id} className="flex flex-wrap items-center gap-x-4 gap-y-1 py-3">
                    <span className="font-medium">{formatShortDate(r.sleep_date)}</span>
                    <span>{formatDuration(r.duration_minutes)}</span>
                    <span className="text-sm text-muted-foreground">
                      {SLEEP_QUALITY_LABELS[r.quality]} ({r.quality} of 5)
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
