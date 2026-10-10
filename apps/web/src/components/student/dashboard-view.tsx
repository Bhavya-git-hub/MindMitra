"use client";

import {
  ArrowRight,
  CalendarDays,
  CircleCheck,
  Flame,
  HeartPulse,
  MoonStar,
  NotebookPen,
  Smile,
  Waves,
} from "lucide-react";
import Link from "next/link";
import * as React from "react";

import { SectionCard } from "@/components/cards/section-card";
import { TrendChart } from "@/components/charts";
import { PageHeader } from "@/components/layout/page-header";
import { DisclaimerBanner } from "@/components/safety/disclaimer-banner";
import { EmptyState } from "@/components/states/empty-state";
import { DataView } from "@/components/student/data-view";
import { MetricCard } from "@/components/student/metric-card";
import { RecommendationList } from "@/components/student/recommendation-list";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import type { Dashboard } from "@/lib/api/student-schemas";
import { useAuth } from "@/lib/auth/auth-context";
import { firstName, formatDateTime, formatDuration, modeLabel, titleCase } from "@/lib/format";
import { useQuery } from "@/lib/hooks/use-query";
import { useStudentApi } from "@/lib/hooks/use-student-api";
import { chartRows, hasAny } from "@/lib/trend-data";
import { MOOD_LABELS } from "@/lib/student-options";

function score(value: number | null, max = 5): string | null {
  return value === null ? null : `${Math.round(value * 10) / 10} / ${max}`;
}

export function DashboardView() {
  const api = useStudentApi();
  const { user } = useAuth();
  const query = useQuery("dashboard", () => api.dashboard());
  return (
    <>
      <PageHeader
        title={user ? `Hello, ${firstName(user.full_name)}` : "Hello"}
        description="A quick look at how things have been, in your own words and numbers."
        actions={
          <Button asChild variant="outline">
            <Link href="/student/wellness">
              Wellness details <ArrowRight aria-hidden="true" />
            </Link>
          </Button>
        }
      />
      <DisclaimerBanner />
      <DataView query={query}>{(d) => <DashboardBody data={d} />}</DataView>
    </>
  );
}

function CheckInCard({ data }: { data: Dashboard }) {
  const { check_in: c } = data;
  const mood = data.mood.today;
  if (!c.done_today) {
    return (
      <SectionCard
        title="Daily check-in"
        description="Take a minute to notice how you're doing. Only you see your notes."
        action={<NotebookPen className="size-5 text-muted-foreground" aria-hidden="true" />}
      >
        <div className="flex flex-wrap items-center gap-4">
          <Button asChild size="lg">
            <Link href="/student/check-in">Check in now</Link>
          </Button>
          {c.streak_days > 0 && (
            <Badge variant="accent">
              <Flame aria-hidden="true" /> {c.streak_days}-day streak. Keep it going!
            </Badge>
          )}
        </div>
      </SectionCard>
    );
  }
  return (
    <SectionCard
      title="You've checked in today"
      description={
        mood !== null
          ? `You rated your mood ${Math.round(mood)} of 5 (${MOOD_LABELS[Math.round(mood)] ?? "logged"}). Thank you for taking a moment.`
          : "Thank you for taking a moment."
      }
      action={<CircleCheck className="size-5 text-success" aria-hidden="true" />}
    >
      <div className="flex flex-wrap items-center gap-3">
        {c.streak_days > 1 && (
          <Badge variant="accent">
            <Flame aria-hidden="true" /> {c.streak_days}-day streak
          </Badge>
        )}
        {c.emotions_today.map((e) => (
          <Badge key={e} variant="secondary">
            {e}
          </Badge>
        ))}
        <Button asChild variant="ghost" size="sm">
          <Link href="/student/check-in">Add another check-in</Link>
        </Button>
      </div>
    </SectionCard>
  );
}

function AppointmentCard({ data }: { data: Dashboard }) {
  const appt = data.upcoming_appointment;
  if (!appt) {
    return (
      <EmptyState
        icon={CalendarDays}
        title="No upcoming appointments"
        description="Talking to a counsellor is open to every student. You can look at who's available whenever you like."
        action={
          <Button asChild variant="outline">
            <Link href="/student/therapists">Find a therapist</Link>
          </Button>
        }
      />
    );
  }
  return (
    <SectionCard
      title="Next appointment"
      description={`With ${appt.therapist_name}`}
      action={<CalendarDays className="size-5 text-muted-foreground" aria-hidden="true" />}
      footer={
        <Button asChild variant="outline" size="sm">
          <Link href="/student/appointments">Manage appointments</Link>
        </Button>
      }
    >
      <p className="text-lg font-semibold">{formatDateTime(appt.starts_at)}</p>
      <p className="mt-1 flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
        <span>{modeLabel(appt.mode)}</span>
        <span aria-hidden="true">·</span>
        <span>
          {formatDuration(
            Math.round(
              (new Date(appt.ends_at).getTime() - new Date(appt.starts_at).getTime()) / 60_000,
            ),
          )}
        </span>
        <Badge variant={appt.status === "confirmed" ? "success" : "info"}>
          {appt.status === "requested" ? "Waiting for confirmation" : titleCase(appt.status)}
        </Badge>
      </p>
    </SectionCard>
  );
}

function DashboardBody({ data }: { data: Dashboard }) {
  const sleepMinutes = data.sleep.last_night_minutes ?? data.sleep.average_minutes_7d;
  const trendFields = (["mood", "stress"] as const).filter((f) => hasAny(data.recent_trends, f));
  return (
    <div className="space-y-6">
      <CheckInCard data={data} />

      <section aria-labelledby="indicators-heading" className="space-y-3">
        <h2 id="indicators-heading" className="text-lg font-semibold">
          How things look
        </h2>
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          <MetricCard
            label="Mood"
            icon={Smile}
            value={score(data.mood.today ?? data.mood.average_7d)}
            indicator={data.mood.indicator?.label}
            direction={data.mood.direction}
            empty="No check-in yet"
          />
          <MetricCard
            label="Stress"
            icon={Waves}
            value={score(data.stress.today ?? data.stress.average_7d)}
            indicator={data.stress.indicator?.label}
            direction={data.stress.direction}
            empty="Not logged yet"
          />
          <MetricCard
            label="Sleep"
            icon={MoonStar}
            value={sleepMinutes === null ? null : formatDuration(Math.round(sleepMinutes))}
            indicator={data.sleep.indicator?.label}
            direction={data.sleep.direction}
            empty="Not logged yet"
          />
          <MetricCard
            label="Wellbeing check"
            icon={HeartPulse}
            value={data.wellbeing ? `${data.wellbeing.percent}%` : null}
            indicator={data.wellbeing?.band.label}
            empty="Take the 2-minute check"
          />
        </div>
        <p className="text-sm text-muted-foreground">{data.disclaimer}</p>
      </section>

      <div className="grid gap-6 lg:grid-cols-2">
        <SectionCard
          title="This week"
          description="Your mood and stress over the last 7 days."
          footer={
            <Button asChild variant="ghost" size="sm">
              <Link href="/student/trends">See all trends</Link>
            </Button>
          }
        >
          {trendFields.length > 0 ? (
            <TrendChart
              title="Mood and stress this week"
              data={chartRows(data.recent_trends, ["mood", "stress"])}
              xKey="day"
              yDomain={[1, 5]}
              series={trendFields.map((f) => ({
                key: f,
                label: f === "mood" ? "Mood (5 is best)" : "Stress (5 is highest)",
              }))}
            />
          ) : (
            <EmptyState
              title="Nothing to chart yet"
              description="After a couple of check-ins, your week will appear here."
            />
          )}
        </SectionCard>
        <AppointmentCard data={data} />
      </div>

      <SectionCard
        title="Ideas for you"
        description="Optional suggestions based on what you've shared. Skip any that don't fit."
        footer={
          <Button asChild variant="ghost" size="sm">
            <Link href="/student/recommendations">All suggestions</Link>
          </Button>
        }
      >
        {data.recommendations.length > 0 ? (
          <RecommendationList items={data.recommendations} compact />
        ) : (
          <p className="text-sm text-muted-foreground">
            No suggestions right now. They appear as you check in.
          </p>
        )}
      </SectionCard>
    </div>
  );
}
