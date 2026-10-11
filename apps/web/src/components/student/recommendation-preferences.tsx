"use client";

import * as React from "react";

import { SectionCard } from "@/components/cards/section-card";
import { InlineAlert } from "@/components/states/inline-alert";
import { ChipGroup } from "@/components/student/chip-group";
import { DataView } from "@/components/student/data-view";
import { NativeSelect, SaveButton, useSubmit } from "@/components/student/form-bits";
import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";
import type { RecommendationPreferences } from "@/lib/api/student-schemas";
import { useQuery } from "@/lib/hooks/use-query";
import { useStudentApi } from "@/lib/hooks/use-student-api";
import { RESOURCE_TYPE_LABELS, SUGGESTION_AREA_LABELS } from "@/lib/student-options";
import { notify } from "@/lib/toast";

const TIME_LIMITS = [5, 10, 15, 30, 60];

const toLabels = (values: string[], labels: Record<string, string>) =>
  values.map((v) => labels[v] ?? v);

function fromLabels(chosen: string[], all: string[], labels: Record<string, string>) {
  return all.filter((v) => chosen.includes(labels[v] ?? v));
}

/** What suits the student: formats, a time limit, topics to leave alone, and the indicators. */
export function RecommendationPreferencesCard() {
  const api = useStudentApi();
  const query = useQuery("recommendation-preferences", () => api.recommendationPreferences());
  return (
    <DataView query={query} skeleton={null}>
      {(prefs) => (
        <PreferencesForm key={JSON.stringify(prefs)} prefs={prefs} onSaved={query.reload} />
      )}
    </DataView>
  );
}

function PreferencesForm({
  prefs,
  onSaved,
}: {
  prefs: RecommendationPreferences;
  onSaved: () => Promise<unknown> | void;
}) {
  const api = useStudentApi();
  const save = useSubmit();
  const [formats, setFormats] = React.useState(prefs.preferred_formats);
  const [muted, setMuted] = React.useState(prefs.muted_areas);
  const [minutes, setMinutes] = React.useState<string>(prefs.max_minutes?.toString() ?? "");
  const [useIndicators, setUseIndicators] = React.useState(prefs.use_indicators);
  const limits = Array.from(
    new Set([...TIME_LIMITS, ...(prefs.max_minutes ? [prefs.max_minutes] : [])]),
  ).sort((a, b) => a - b);

  return (
    <SectionCard
      title="What suits you"
      description="Tell MindMitra what you like and it will tune your suggestions. Only you can see these settings."
    >
      <form
        className="grid gap-5"
        onSubmit={(e) => {
          e.preventDefault();
          void save.run(async () => {
            await api.updateRecommendationPreferences({
              preferred_formats: formats,
              max_minutes: minutes === "" ? null : Number(minutes),
              muted_areas: muted,
              use_indicators: useIndicators,
            });
            await onSaved();
            notify.success("Your preferences are saved.");
          }, "We couldn't save your preferences.");
        }}
      >
        {save.error && <InlineAlert tone="destructive">{save.error}</InlineAlert>}
        <ChipGroup
          legend="Kinds of resource you like"
          hint="Leave empty if you have no preference."
          options={toLabels(prefs.available_formats, RESOURCE_TYPE_LABELS)}
          value={toLabels(formats, RESOURCE_TYPE_LABELS)}
          onChange={(chosen) =>
            setFormats(fromLabels(chosen, prefs.available_formats, RESOURCE_TYPE_LABELS))
          }
          max={prefs.available_formats.length}
        />
        <div className="grid gap-2 sm:max-w-xs">
          <Label htmlFor="rec-minutes">Longest you want a resource to take</Label>
          <NativeSelect
            id="rec-minutes"
            value={minutes}
            onChange={(e) => setMinutes(e.target.value)}
          >
            <option value="">No limit</option>
            {limits.map((m) => (
              <option key={m} value={m}>
                {m} minutes
              </option>
            ))}
          </NativeSelect>
        </div>
        <ChipGroup
          legend="Don't suggest anything about"
          hint="You can change this any time. Choosing a topic hides its suggestions."
          options={toLabels(prefs.available_areas, SUGGESTION_AREA_LABELS)}
          value={toLabels(muted, SUGGESTION_AREA_LABELS)}
          onChange={(chosen) =>
            setMuted(fromLabels(chosen, prefs.available_areas, SUGGESTION_AREA_LABELS))
          }
          max={prefs.available_areas.length}
        />
        <div className="flex items-start gap-3">
          <Checkbox
            id="rec-indicators"
            checked={useIndicators}
            onCheckedChange={(c) => setUseIndicators(c === true)}
            className="mt-0.5"
          />
          <div className="grid gap-1">
            <Label htmlFor="rec-indicators" className="font-normal">
              Use my wellness indicators to tune suggestions
            </Label>
            <p className="text-sm text-muted-foreground">
              Indicators look at the pattern of your check-ins (never what you write in your notes).
              Turn this off and suggestions use only your recent check-ins, goals and settings.
            </p>
          </div>
        </div>
        <div>
          <SaveButton pending={save.pending}>Save preferences</SaveButton>
        </div>
      </form>
    </SectionCard>
  );
}
