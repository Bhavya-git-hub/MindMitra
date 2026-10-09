"use client";

import { Activity, Heart, Moon } from "lucide-react";
import * as React from "react";
import { useForm } from "react-hook-form";

import { SectionCard } from "@/components/cards/section-card";
import { StatCard } from "@/components/cards/stat-card";
import { BarSeriesChart, DonutChart, Sparkline, TrendChart } from "@/components/charts";
import {
  CheckboxField,
  PasswordField,
  SelectField,
  SubmitButton,
  TextareaField,
  TextField,
} from "@/components/forms/fields";
import { PageHeader } from "@/components/layout/page-header";
import { SkipLink } from "@/components/layout/skip-link";
import { ThemeToggle } from "@/components/layout/theme-toggle";
import { useModal } from "@/components/providers/modal-provider";
import { DisclaimerBanner } from "@/components/safety/disclaimer-banner";
import { GetHelpButton } from "@/components/safety/get-help-button";
import { ComingSoon } from "@/components/states/coming-soon";
import { EmptyState } from "@/components/states/empty-state";
import { ErrorState } from "@/components/states/error-state";
import { InlineAlert } from "@/components/states/inline-alert";
import { LoadingState } from "@/components/states/loading-state";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Form } from "@/components/ui/form";
import { Skeleton } from "@/components/ui/skeleton";
import { notify } from "@/lib/toast";

// Synthetic data only.
const MOOD_WEEK = [
  { day: "Mon", mood: 3, energy: 2 },
  { day: "Tue", mood: 3, energy: 3 },
  { day: "Wed", mood: 4, energy: 3 },
  { day: "Thu", mood: 2, energy: 2 },
  { day: "Fri", mood: 4, energy: 4 },
  { day: "Sat", mood: 5, energy: 4 },
  { day: "Sun", mood: 4, energy: 3 },
];
const SESSIONS = [
  { week: "Wk 1", completed: 8, rescheduled: 2 },
  { week: "Wk 2", completed: 11, rescheduled: 1 },
  { week: "Wk 3", completed: 9, rescheduled: 3 },
  { week: "Wk 4", completed: 12, rescheduled: 2 },
];
const SUPPORT = [
  { name: "Self-guided", value: 46 },
  { name: "Peer circles", value: 24 },
  { name: "Counsellor", value: 30 },
];

interface DemoValues {
  name: string;
  password: string;
  stream: string;
  about: string;
  agree: boolean;
}

const SWATCHES = [
  ["Primary", "bg-primary text-primary-foreground"],
  ["Secondary", "bg-secondary text-secondary-foreground"],
  ["Accent", "bg-accent text-accent-foreground"],
  ["Muted", "bg-muted text-muted-foreground"],
  ["Success", "bg-success-soft text-success"],
  ["Warning", "bg-warning-soft text-warning"],
  ["Info", "bg-info-soft text-info"],
  ["Destructive", "bg-destructive text-destructive-foreground"],
] as const;

export function Showcase() {
  const modal = useModal();
  const form = useForm<DemoValues>({
    defaultValues: { name: "", password: "", stream: "", about: "", agree: false },
  });

  return (
    <div className="bg-calm min-h-dvh">
      <SkipLink />
      <main
        id="main-content"
        tabIndex={-1}
        className="mx-auto max-w-5xl space-y-10 px-4 py-10 outline-none"
      >
        <PageHeader
          title="MindMitra design system"
          description="Calm, warm and clear. Every colour pair here meets WCAG 2.1 AA in light and dark."
          actions={<ThemeToggle />}
        />

        <SectionCard title="Colour">
          <ul className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            {SWATCHES.map(([name, cls]) => (
              <li key={name} className={`rounded-lg px-3 py-4 text-sm font-medium ${cls}`}>
                {name}
              </li>
            ))}
          </ul>
        </SectionCard>

        <SectionCard title="Buttons and badges">
          <div className="flex flex-wrap items-center gap-3">
            <Button>Primary</Button>
            <Button variant="secondary">Secondary</Button>
            <Button variant="outline">Outline</Button>
            <Button variant="ghost">Ghost</Button>
            <Button variant="destructive">Destructive</Button>
            <Button disabled>Disabled</Button>
            <GetHelpButton />
          </div>
          <div className="mt-4 flex flex-wrap gap-2">
            <Badge>Default</Badge>
            <Badge variant="secondary">Secondary</Badge>
            <Badge variant="accent">Accent</Badge>
            <Badge variant="success">Success</Badge>
            <Badge variant="warning">Warning</Badge>
            <Badge variant="info">Info</Badge>
            <Badge variant="outline">Outline</Badge>
          </div>
        </SectionCard>

        <SectionCard title="Feedback: toasts and modals">
          <div className="flex flex-wrap gap-3">
            <Button
              variant="outline"
              onClick={() => notify.success("Saved", "Your changes are safe.")}
            >
              Success toast
            </Button>
            <Button variant="outline" onClick={() => notify.info("Heads up", "A gentle note.")}>
              Info toast
            </Button>
            <Button
              variant="outline"
              onClick={() => notify.error("That didn't work", "Please try again.")}
            >
              Error toast
            </Button>
            <Button
              variant="outline"
              onClick={async () => {
                const ok = await modal.confirm({
                  title: "Remove this reminder?",
                  description: "You can add it again any time.",
                  confirmLabel: "Remove",
                  destructive: true,
                });
                notify.info(ok ? "Reminder removed" : "Kept it");
              }}
            >
              Confirm dialog
            </Button>
            <Button
              variant="outline"
              onClick={() =>
                modal.open({
                  title: "A general dialog",
                  description: "Focus is trapped here and returns to the button when you close it.",
                  content: (close) => (
                    <Button onClick={close} className="w-full">
                      Close
                    </Button>
                  ),
                })
              }
            >
              Open dialog
            </Button>
          </div>
        </SectionCard>

        <SectionCard title="Inline messages">
          <div className="grid gap-3">
            <InlineAlert tone="info" title="Good to know">
              Informational messages are calm and polite.
            </InlineAlert>
            <InlineAlert tone="success">Your check-in was saved.</InlineAlert>
            <InlineAlert tone="warning" title="Almost there">
              Something needs a second look.
            </InlineAlert>
            <InlineAlert tone="destructive">
              We couldn&apos;t save that. Please try again.
            </InlineAlert>
            <DisclaimerBanner />
          </div>
        </SectionCard>

        <SectionCard title="Form components">
          <Form {...form}>
            <form
              className="grid max-w-md gap-4"
              onSubmit={form.handleSubmit(() => notify.success("Form submitted"))}
            >
              <TextField<DemoValues>
                name="name"
                label="Preferred name"
                description="What should we call you?"
              />
              <PasswordField<DemoValues>
                name="password"
                label="Password"
                autoComplete="new-password"
              />
              <SelectField<DemoValues>
                name="stream"
                label="Stream"
                options={[
                  { value: "sci", label: "Science" },
                  { value: "arts", label: "Arts" },
                ]}
              />
              <TextareaField<DemoValues> name="about" label="Anything on your mind?" rows={3} />
              <CheckboxField<DemoValues> name="agree" label="I'd like gentle reminders" />
              <SubmitButton pending={false}>Save</SubmitButton>
            </form>
          </Form>
        </SectionCard>

        <section aria-labelledby="stats" className="space-y-4">
          <h2 id="stats" className="text-lg font-semibold">
            Cards and stats
          </h2>
          <div className="grid gap-4 sm:grid-cols-3">
            <StatCard
              label="Check-ins this week"
              value={5}
              icon={Heart}
              trend="up"
              trendLabel="vs last week"
            />
            <StatCard label="Average sleep" value="7.2 h" icon={Moon} trend="flat" hint="steady" />
            <StatCard
              label="Mood"
              value="3.6"
              icon={Activity}
              visual={<Sparkline values={MOOD_WEEK.map((d) => d.mood)} />}
            />
          </div>
        </section>

        <SectionCard
          title="Charts"
          description="Synthetic data. Each chart has a hidden data table for screen readers."
        >
          <div className="grid gap-8 lg:grid-cols-2">
            <TrendChart
              title="Mood and energy this week"
              description="Scale of 1 (low) to 5 (high)"
              data={MOOD_WEEK}
              xKey="day"
              series={[
                { key: "mood", label: "Mood" },
                { key: "energy", label: "Energy" },
              ]}
              yDomain={[1, 5]}
            />
            <BarSeriesChart
              title="Sessions per week"
              data={SESSIONS}
              xKey="week"
              series={[
                { key: "completed", label: "Completed" },
                { key: "rescheduled", label: "Rescheduled" },
              ]}
            />
            <DonutChart title="Where students find support" data={SUPPORT} />
          </div>
        </SectionCard>

        <section aria-labelledby="states" className="space-y-4">
          <h2 id="states" className="text-lg font-semibold">
            Loading, empty and error states
          </h2>
          <div className="grid gap-4 lg:grid-cols-2">
            <SectionCard title="Loading" headingLevel="h3">
              <LoadingState label="Fetching your week…" />
              <div className="space-y-2">
                <Skeleton className="h-4 w-2/3" />
                <Skeleton className="h-4 w-1/2" />
              </div>
            </SectionCard>
            <EmptyState
              icon={Heart}
              title="No check-ins yet"
              description="When you add one, it will show up here."
            />
            <ErrorState onRetry={() => notify.info("Retrying…")} reference="req_demo123" />
            <ComingSoon what="Appointments" />
          </div>
        </section>
      </main>
    </div>
  );
}
