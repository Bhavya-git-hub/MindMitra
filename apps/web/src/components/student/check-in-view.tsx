"use client";

import { Loader2 } from "lucide-react";
import Link from "next/link";
import * as React from "react";

import { SectionCard } from "@/components/cards/section-card";
import { PageHeader } from "@/components/layout/page-header";
import { InlineAlert } from "@/components/states/inline-alert";
import { ChipGroup } from "@/components/student/chip-group";
import { RatingScale } from "@/components/student/rating-scale";
import { SupportCallout } from "@/components/student/support-callout";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { describeError } from "@/lib/api/errors";
import type { CheckInInput } from "@/lib/api/student-api";
import type { CheckInResult } from "@/lib/api/student-schemas";
import { formatDuration } from "@/lib/format";
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

export function CheckInView() {
  const api = useStudentApi();
  const [mood, setMood] = React.useState<number>();
  const [emotions, setEmotions] = React.useState<string[]>([]);
  const [energy, setEnergy] = React.useState<number>();
  const [stress, setStress] = React.useState<number>();
  const [stressors, setStressors] = React.useState<string[]>([]);
  const [addSleep, setAddSleep] = React.useState(false);
  const [bed, setBed] = React.useState("23:00");
  const [wake, setWake] = React.useState("07:00");
  const [quality, setQuality] = React.useState<number>();
  const [note, setNote] = React.useState("");
  const [submitting, setSubmitting] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [moodError, setMoodError] = React.useState<string>();
  const [result, setResult] = React.useState<CheckInResult | null>(null);
  const resultRef = React.useRef<HTMLDivElement>(null);

  React.useEffect(() => {
    if (result) resultRef.current?.focus();
  }, [result]);

  const sleepTimes = addSleep ? sleepWindow(bed, wake) : null;

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    if (mood === undefined) {
      setMoodError("Choose how you're feeling to continue.");
      return;
    }
    if (addSleep && (!sleepTimes || quality === undefined)) {
      setError("Add your bedtime, wake time and how well you slept, or untick the sleep section.");
      return;
    }
    const input: CheckInInput = {
      mood_score: mood,
      emotions,
      energy_level: energy,
      stress_level: stress,
      stressors: stress === undefined ? undefined : stressors,
      note: note.trim() || undefined,
      sleep:
        addSleep && sleepTimes && quality !== undefined
          ? { bedtime: sleepTimes.bedtime, wake_time: sleepTimes.wake_time, quality }
          : undefined,
    };
    setSubmitting(true);
    try {
      setResult(await api.checkIn(input));
    } catch (e) {
      setError(describeError(e, "We couldn't save your check-in. Please try again."));
    } finally {
      setSubmitting(false);
    }
  }

  if (result) {
    return (
      <>
        <PageHeader title="Thanks for checking in" />
        <div ref={resultRef} tabIndex={-1} className="space-y-4 outline-none">
          <p className="text-muted-foreground">
            Your check-in is saved. Noticing how you feel is a good habit, whatever the number.
          </p>
          {result.support && <SupportCallout message={result.support.message} />}
          <div className="flex flex-wrap gap-2">
            <Button asChild>
              <Link href="/student">Back to my dashboard</Link>
            </Button>
            <Button asChild variant="outline">
              <Link href="/student/trends">See my trends</Link>
            </Button>
          </div>
        </div>
      </>
    );
  }

  return (
    <>
      <PageHeader
        title="Daily check-in"
        description="A minute to notice how you are. Only the first question is required."
      />
      <form onSubmit={(e) => void submit(e)} noValidate className="space-y-6">
        <SectionCard title="How are you feeling right now?">
          <div className="space-y-6">
            <RatingScale
              legend="Mood"
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
          </div>
        </SectionCard>

        <SectionCard title="Stress (optional)">
          <div className="space-y-6">
            <RatingScale
              legend="How stressed do you feel?"
              labels={STRESS_LABELS}
              value={stress}
              onChange={setStress}
              optional
            />
            {stress !== undefined && (
              <ChipGroup
                legend="What's contributing?"
                options={STRESSORS}
                value={stressors}
                onChange={setStressors}
              />
            )}
          </div>
        </SectionCard>

        <SectionCard title="Last night's sleep (optional)">
          <div className="space-y-4">
            <div className="flex items-center gap-3">
              <Checkbox
                id="add-sleep"
                checked={addSleep}
                onCheckedChange={(v) => setAddSleep(v === true)}
              />
              <Label htmlFor="add-sleep">Add last night&apos;s sleep</Label>
            </div>
            {addSleep && (
              <div className="space-y-4">
                <div className="grid gap-4 sm:grid-cols-2">
                  <div className="space-y-2">
                    <Label htmlFor="bedtime">I went to bed at</Label>
                    <Input
                      id="bedtime"
                      type="time"
                      value={bed}
                      onChange={(e) => setBed(e.target.value)}
                    />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="waketime">I woke up at</Label>
                    <Input
                      id="waketime"
                      type="time"
                      value={wake}
                      onChange={(e) => setWake(e.target.value)}
                    />
                  </div>
                </div>
                {sleepTimes && (
                  <p className="text-sm text-muted-foreground" aria-live="polite">
                    That&apos;s about {formatDuration(sleepTimes.durationMinutes)} of sleep.
                  </p>
                )}
                <RatingScale
                  legend="How well did you sleep?"
                  labels={SLEEP_QUALITY_LABELS}
                  value={quality}
                  onChange={setQuality}
                />
              </div>
            )}
          </div>
        </SectionCard>

        <SectionCard
          title="Anything you'd like to remember? (optional)"
          description="Private to you. Your therapist never sees your notes, even if you share your scores."
        >
          <div className="space-y-2">
            <Label htmlFor="note" className="sr-only">
              Private note
            </Label>
            <Textarea
              id="note"
              value={note}
              onChange={(e) => setNote(e.target.value)}
              maxLength={2000}
              rows={4}
            />
          </div>
        </SectionCard>

        {error && (
          <InlineAlert tone="destructive" title="Something needs attention">
            {error}
          </InlineAlert>
        )}
        <Button type="submit" size="lg" disabled={submitting}>
          {submitting && <Loader2 className="animate-spin" aria-hidden="true" />}
          Save check-in
        </Button>
      </form>
    </>
  );
}
