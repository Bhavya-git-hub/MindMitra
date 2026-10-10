import type { LucideIcon } from "lucide-react";

import { StatCard, type Trend } from "@/components/cards/stat-card";

type Direction = "up" | "steady" | "down" | null;

const TREND: Record<"up" | "steady" | "down", Trend> = { up: "up", steady: "flat", down: "down" };

/** A wellbeing number with its plain-language label, and the week-on-week direction if known. */
export function MetricCard({
  label,
  value,
  indicator,
  direction,
  empty,
  icon,
}: {
  label: string;
  /** Already formatted, or null when nothing has been logged. */
  value: string | null;
  indicator?: string | null;
  direction?: Direction;
  empty: string;
  icon: LucideIcon;
}) {
  return (
    <StatCard
      label={label}
      value={value ?? "—"}
      hint={value === null ? empty : (indicator ?? undefined)}
      icon={icon}
      trend={value !== null && direction ? TREND[direction] : undefined}
      trendLabel="vs last week"
    />
  );
}
