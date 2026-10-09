"use client";

import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { AXIS_PROPS, ChartFrame, seriesColor } from "./chart-frame";
import type { ChartDatum, Series } from "./trend-chart";

const TOOLTIP_STYLE = {
  background: "var(--popover)",
  border: "1px solid var(--border)",
  borderRadius: 12,
  color: "var(--popover-foreground)",
  fontSize: 13,
} as const;

/** Compare categories (for example sessions per week). */
export function BarSeriesChart({
  title,
  description,
  data,
  xKey,
  series,
  height,
}: {
  title: string;
  description?: string;
  data: ChartDatum[];
  xKey: string;
  series: Series[];
  height?: number;
}) {
  return (
    <ChartFrame
      title={title}
      description={description}
      height={height}
      table={{
        caption: title,
        columns: [xKey, ...series.map((s) => s.label)],
        rows: data.map((d) => [d[xKey] ?? "", ...series.map((s) => d[s.key] ?? "")]),
      }}
    >
      <ResponsiveContainer width="100%" height="100%">
        <BarChart
          accessibilityLayer={false}
          data={data}
          margin={{ top: 8, right: 12, bottom: 0, left: -16 }}
        >
          <CartesianGrid stroke="var(--border)" strokeDasharray="3 3" vertical={false} />
          <XAxis dataKey={xKey} {...AXIS_PROPS} />
          <YAxis {...AXIS_PROPS} axisLine={false} />
          <Tooltip contentStyle={TOOLTIP_STYLE} cursor={{ fill: "var(--secondary)" }} />
          {series.length > 1 && <Legend />}
          {series.map((s, i) => (
            <Bar
              key={s.key}
              dataKey={s.key}
              name={s.label}
              fill={seriesColor(i)}
              radius={[6, 6, 0, 0]}
              isAnimationActive={false}
            />
          ))}
        </BarChart>
      </ResponsiveContainer>
    </ChartFrame>
  );
}
