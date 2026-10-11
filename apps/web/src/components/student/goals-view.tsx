"use client";

import { Target } from "lucide-react";
import * as React from "react";

import { SectionCard } from "@/components/cards/section-card";
import { PageHeader } from "@/components/layout/page-header";
import { EmptyState } from "@/components/states/empty-state";
import { InlineAlert } from "@/components/states/inline-alert";
import { GoalProgress, useWellnessAnalytics } from "@/components/student/analytics-sections";
import { DataView } from "@/components/student/data-view";
import { NativeSelect, SaveButton, useSubmit } from "@/components/student/form-bits";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import type { GoalInput, GoalPatch } from "@/lib/api/student-api";
import { GOAL_CATEGORIES, type Goal, type GoalCategory } from "@/lib/api/student-schemas";
import { formatShortDate, titleCase } from "@/lib/format";
import { useQuery } from "@/lib/hooks/use-query";
import { useStudentApi } from "@/lib/hooks/use-student-api";
import { GOAL_CATEGORY_LABELS } from "@/lib/student-options";
import { notify } from "@/lib/toast";

function toNumber(text: string): number | undefined {
  if (text.trim() === "") return undefined;
  const n = Number(text);
  return Number.isFinite(n) ? n : undefined;
}

function NewGoalForm({ onCreated }: { onCreated: () => Promise<void> }) {
  const api = useStudentApi();
  const [title, setTitle] = React.useState("");
  const [category, setCategory] = React.useState<GoalCategory>("sleep");
  const [target, setTarget] = React.useState("");
  const [unit, setUnit] = React.useState("");
  const [date, setDate] = React.useState("");
  const [description, setDescription] = React.useState("");
  const [titleError, setTitleError] = React.useState<string>();
  const { pending, error, run } = useSubmit();

  function submit(event: React.FormEvent) {
    event.preventDefault();
    if (title.trim().length < 3) {
      setTitleError("Give your goal a short name (at least 3 letters).");
      return;
    }
    const input: GoalInput = {
      title: title.trim(),
      category,
      description: description.trim() || undefined,
      target_value: toNumber(target),
      unit: unit.trim() || undefined,
      target_date: date || undefined,
    };
    void run(async () => {
      await api.createGoal(input);
      setTitle("");
      setTarget("");
      setUnit("");
      setDate("");
      setDescription("");
      notify.success("Goal added");
      await onCreated();
    });
  }

  return (
    <form onSubmit={submit} noValidate className="grid gap-4 sm:grid-cols-2">
      <div className="space-y-2 sm:col-span-2">
        <Label htmlFor="goal-title">What would you like to work on?</Label>
        <Input
          id="goal-title"
          value={title}
          onChange={(e) => {
            setTitle(e.target.value);
            setTitleError(undefined);
          }}
          maxLength={120}
          aria-invalid={titleError ? true : undefined}
          aria-describedby={titleError ? "goal-title-error" : undefined}
          placeholder="For example: Wind down before midnight"
        />
        {titleError && (
          <p id="goal-title-error" className="text-sm text-destructive">
            {titleError}
          </p>
        )}
      </div>
      <div className="space-y-2">
        <Label htmlFor="goal-category">Area</Label>
        <NativeSelect
          id="goal-category"
          value={category}
          onChange={(e) => setCategory(e.target.value as GoalCategory)}
        >
          {GOAL_CATEGORIES.map((c) => (
            <option key={c} value={c}>
              {GOAL_CATEGORY_LABELS[c]}
            </option>
          ))}
        </NativeSelect>
      </div>
      <div className="space-y-2">
        <Label htmlFor="goal-date">Aim to finish by (optional)</Label>
        <Input id="goal-date" type="date" value={date} onChange={(e) => setDate(e.target.value)} />
      </div>
      <div className="space-y-2">
        <Label htmlFor="goal-target">Target number (optional)</Label>
        <Input
          id="goal-target"
          type="number"
          inputMode="decimal"
          min={0}
          value={target}
          onChange={(e) => setTarget(e.target.value)}
        />
      </div>
      <div className="space-y-2">
        <Label htmlFor="goal-unit">Measured in (optional)</Label>
        <Input
          id="goal-unit"
          value={unit}
          onChange={(e) => setUnit(e.target.value)}
          maxLength={30}
          placeholder="nights, walks, minutes…"
        />
      </div>
      <div className="space-y-2 sm:col-span-2">
        <Label htmlFor="goal-description">Notes (optional)</Label>
        <Textarea
          id="goal-description"
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          maxLength={500}
          rows={2}
        />
      </div>
      {error && (
        <div className="sm:col-span-2">
          <InlineAlert tone="destructive">{error}</InlineAlert>
        </div>
      )}
      <div className="sm:col-span-2">
        <SaveButton pending={pending}>Add goal</SaveButton>
      </div>
    </form>
  );
}

function GoalCard({ goal, onChange }: { goal: Goal; onChange: () => Promise<void> }) {
  const api = useStudentApi();
  const [value, setValue] = React.useState(String(goal.current_value));
  const { pending, error, run } = useSubmit();
  const open = goal.status === "active" || goal.status === "paused";
  const hasTarget = goal.target_value !== null;

  function patch(body: GoalPatch, message: string) {
    void run(async () => {
      await api.updateGoal(goal.id, body);
      notify.success(message);
      await onChange();
    });
  }

  return (
    <li className="space-y-3 rounded-xl border bg-card p-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <h3 className="font-medium">{goal.title}</h3>
          <p className="text-sm text-muted-foreground">
            {GOAL_CATEGORY_LABELS[goal.category] ?? titleCase(goal.category)}
            {goal.target_date ? ` · by ${formatShortDate(goal.target_date)}` : ""}
          </p>
        </div>
        <Badge
          variant={
            goal.status === "completed" ? "success" : goal.status === "active" ? "info" : "outline"
          }
        >
          {goal.status === "abandoned" ? "Let go" : titleCase(goal.status)}
        </Badge>
      </div>
      {goal.description && <p className="text-sm">{goal.description}</p>}
      {hasTarget && goal.progress_percent !== null && (
        <div className="space-y-1">
          <div
            role="progressbar"
            aria-label={`Progress on ${goal.title}`}
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={goal.progress_percent}
            className="h-2 overflow-hidden rounded-full bg-secondary"
          >
            <div
              className="h-full rounded-full bg-primary"
              style={{ width: `${Math.min(100, goal.progress_percent)}%` }}
            />
          </div>
          <p className="text-sm text-muted-foreground">
            {goal.current_value} of {goal.target_value} {goal.unit ?? ""} ({goal.progress_percent}
            %)
          </p>
        </div>
      )}
      {open && (
        <form
          className="flex flex-wrap items-end gap-3"
          noValidate
          onSubmit={(e) => {
            e.preventDefault();
            const n = toNumber(value);
            if (n === undefined || n < 0) return;
            patch({ current_value: n }, "Progress saved");
          }}
        >
          <div className="space-y-1">
            <Label htmlFor={`progress-${goal.id}`} className="text-sm">
              Progress so far{goal.unit ? ` (${goal.unit})` : ""}
            </Label>
            <Input
              id={`progress-${goal.id}`}
              type="number"
              inputMode="decimal"
              min={0}
              value={value}
              onChange={(e) => setValue(e.target.value)}
              className="w-32"
            />
          </div>
          <SaveButton pending={pending} variant="outline" size="sm">
            Save progress
          </SaveButton>
        </form>
      )}
      {error && <InlineAlert tone="destructive">{error}</InlineAlert>}
      {open && (
        <div className="flex flex-wrap gap-2">
          <Button
            size="sm"
            variant="outline"
            disabled={pending}
            onClick={() => patch({ status: "completed" }, "Well done")}
          >
            Mark as done
          </Button>
          <Button
            size="sm"
            variant="ghost"
            disabled={pending}
            onClick={() =>
              patch(
                { status: goal.status === "active" ? "paused" : "active" },
                goal.status === "active" ? "Goal paused" : "Goal resumed",
              )
            }
          >
            {goal.status === "active" ? "Pause" : "Resume"}
          </Button>
          <Button
            size="sm"
            variant="ghost"
            disabled={pending}
            onClick={() => patch({ status: "abandoned" }, "Goal let go. That's okay.")}
          >
            Let it go
          </Button>
        </div>
      )}
    </li>
  );
}

export function GoalsView() {
  const api = useStudentApi();
  const goals = useQuery("goals", () => api.goals());
  const analytics = useWellnessAnalytics();
  // Changing a goal changes its figures too, so both are reloaded together.
  const reload = async () => {
    await Promise.all([goals.reload(), analytics.reload()]);
  };

  return (
    <>
      <PageHeader
        title="Goals"
        description="Small, kind goals for the things that help you feel well. Change them any time."
      />
      <SectionCard title="Add a goal">
        <NewGoalForm onCreated={reload} />
      </SectionCard>
      <DataView query={goals}>
        {(rows) => {
          const open = rows.filter((g) => g.status === "active" || g.status === "paused");
          const closed = rows.filter((g) => !(g.status === "active" || g.status === "paused"));
          return rows.length === 0 ? (
            <EmptyState
              icon={Target}
              title="No goals yet"
              description="Start with one small thing, like a regular bedtime or a short walk."
            />
          ) : (
            <>
              {open.length > 0 && (
                <SectionCard title="In progress">
                  <ul className="grid gap-3">
                    {open.map((g) => (
                      <GoalCard key={g.id} goal={g} onChange={reload} />
                    ))}
                  </ul>
                </SectionCard>
              )}
              {closed.length > 0 && (
                <SectionCard title="Finished">
                  <ul className="grid gap-3">
                    {closed.map((g) => (
                      <GoalCard key={g.id} goal={g} onChange={reload} />
                    ))}
                  </ul>
                </SectionCard>
              )}
              <GoalProgress query={analytics} />
            </>
          );
        }}
      </DataView>
    </>
  );
}
