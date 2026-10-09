"use client";

import { Cell, Pie, PieChart, ResponsiveContainer } from "recharts";

import { ChartFrame, seriesColor } from "./chart-frame";

export interface Slice {
  name: string;
  value: number;
}

/** Parts of a whole. The legend is real text (name, count, share) beside the ring. */
export function DonutChart({
  title,
  description,
  data,
  height = 200,
}: {
  title: string;
  description?: string;
  data: Slice[];
  height?: number;
}) {
  const total = data.reduce((sum, s) => sum + s.value, 0);
  return (
    <div className="flex flex-col gap-4 sm:flex-row sm:items-center">
      <ChartFrame
        title={title}
        description={description}
        height={height}
        className="sm:max-w-xs"
        table={{
          caption: title,
          columns: ["Group", "Count"],
          rows: data.map((s) => [s.name, s.value]),
        }}
      >
        <ResponsiveContainer width="100%" height="100%">
          <PieChart accessibilityLayer={false}>
            <Pie
              rootTabIndex={-1}
              data={data}
              dataKey="value"
              nameKey="name"
              innerRadius="62%"
              outerRadius="92%"
              paddingAngle={2}
              stroke="var(--card)"
              strokeWidth={2}
              isAnimationActive={false}
            >
              {data.map((s, i) => (
                <Cell key={s.name} fill={seriesColor(i)} />
              ))}
            </Pie>
          </PieChart>
        </ResponsiveContainer>
      </ChartFrame>
      <ul className="grid gap-2 text-sm">
        {data.map((s, i) => (
          <li key={s.name} className="flex items-center gap-2">
            <span
              aria-hidden="true"
              className="size-3 shrink-0 rounded-sm"
              style={{ background: seriesColor(i) }}
            />
            <span>{s.name}</span>
            <span className="text-muted-foreground">
              {total > 0 ? `${s.value} (${Math.round((s.value / total) * 100)}%)` : String(s.value)}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}
