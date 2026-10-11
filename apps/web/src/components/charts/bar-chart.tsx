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

import {
  AXIS_PROPS,
  CHART_MARGIN,
  ChartFrame,
  GRID_PROPS,
  TOOLTIP_STYLE,
  seriesColor,
  seriesTable,
} from "./chart-frame";
import type { ChartDatum, Series } from "./trend-chart";

/** Compare categories (for example sessions per week). */
export function BarSeriesChart({
  title,
  description,
  data,
  xKey,
  series,
  height,
  blankLabel,
}: {
  title: string;
  description?: string;
  data: ChartDatum[];
  xKey: string;
  series: Series[];
  height?: number;
  /** What the accessible table says where a value is missing, for example "Fewer than 5". */
  blankLabel?: string;
}) {
  return (
    <ChartFrame
      title={title}
      description={description}
      height={height}
      table={seriesTable(title, data, xKey, series, blankLabel)}
    >
      <ResponsiveContainer width="100%" height="100%">
        <BarChart accessibilityLayer={false} data={data} margin={CHART_MARGIN}>
          <CartesianGrid {...GRID_PROPS} />
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
