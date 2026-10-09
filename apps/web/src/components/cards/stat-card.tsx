import { ArrowDownRight, ArrowUpRight, Minus, type LucideIcon } from "lucide-react";
import * as React from "react";

import { Card, CardContent } from "@/components/ui/card";
import { cn } from "@/lib/utils";

export type Trend = "up" | "down" | "flat";

const TREND_ICON = { up: ArrowUpRight, down: ArrowDownRight, flat: Minus } as const;
const TREND_WORD = { up: "up", down: "down", flat: "unchanged" } as const;

/**
 * A single number with context. The trend is conveyed by an icon and words, not colour alone,
 * and is deliberately neutral: whether "up" is good depends on the measure.
 */
export function StatCard({
  label,
  value,
  hint,
  icon: Icon,
  trend,
  trendLabel,
  visual,
  className,
}: {
  label: string;
  value: string | number;
  hint?: string;
  icon?: LucideIcon;
  trend?: Trend;
  /** e.g. "vs last week" */
  trendLabel?: string;
  /** Optional sparkline or other decoration. */
  visual?: React.ReactNode;
  className?: string;
}) {
  const TrendIcon = trend ? TREND_ICON[trend] : null;
  return (
    <Card className={cn("shadow-soft", className)}>
      <CardContent className="flex items-start justify-between gap-4">
        <div className="min-w-0 space-y-1">
          <p className="text-sm font-medium text-muted-foreground">{label}</p>
          <p className="text-3xl font-semibold tracking-tight">{value}</p>
          {(hint || trend) && (
            <p className="flex items-center gap-1 text-sm text-muted-foreground">
              {TrendIcon && trend && (
                <>
                  <TrendIcon className="size-4" aria-hidden="true" />
                  <span>
                    {TREND_WORD[trend]}
                    {trendLabel ? ` ${trendLabel}` : ""}
                  </span>
                </>
              )}
              {hint && <span>{hint}</span>}
            </p>
          )}
        </div>
        {visual ??
          (Icon && (
            <span className="grid size-10 shrink-0 place-items-center rounded-lg bg-secondary text-secondary-foreground">
              <Icon className="size-5" aria-hidden="true" />
            </span>
          ))}
      </CardContent>
    </Card>
  );
}
