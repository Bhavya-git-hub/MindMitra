import type { ChartDatum } from "@/components/charts";
import type { TrendPoint } from "@/lib/api/student-schemas";
import { formatShortDate } from "@/lib/format";

type Field = "mood" | "energy" | "stress" | "sleep_hours" | "sleep_quality";

function pick(point: TrendPoint, field: Field): number | null {
  if (field === "sleep_hours")
    return point.sleep_minutes === null ? null : Math.round((point.sleep_minutes / 60) * 10) / 10;
  return point[field];
}

/** Chart rows keyed by `day`; a day with nothing logged simply has no value for that series. */
export function chartRows(points: TrendPoint[], fields: Field[]): ChartDatum[] {
  return points.map((p) => {
    const row: ChartDatum = { day: formatShortDate(p.date) };
    for (const f of fields) {
      const v = pick(p, f);
      if (v !== null) row[f] = v;
    }
    return row;
  });
}

export function hasAny(points: TrendPoint[], field: Field): boolean {
  return points.some((p) => pick(p, field) !== null);
}

export function averageOf(points: TrendPoint[], field: Field): number | null {
  const values = points.map((p) => pick(p, field)).filter((v): v is number => v !== null);
  return values.length === 0 ? null : values.reduce((a, b) => a + b, 0) / values.length;
}
