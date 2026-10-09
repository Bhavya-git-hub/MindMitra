"use client";

import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
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
  SERIES_DASH,
  TOOLTIP_STYLE,
  seriesColor,
  seriesTable,
} from "./chart-frame";

export interface Series {
  key: string;
  label: string;
}

export type ChartDatum = Record<string, string | number>;

/** Lines over time (for example a week of check-ins). */
export function TrendChart({
  title,
  description,
  data,
  xKey,
  series,
  yDomain,
  height,
}: {
  title: string;
  description?: string;
  data: ChartDatum[];
  xKey: string;
  series: Series[];
  yDomain?: [number, number];
  height?: number;
}) {
  return (
    <ChartFrame
      title={title}
      description={description}
      height={height}
      table={seriesTable(title, data, xKey, series)}
    >
      <ResponsiveContainer width="100%" height="100%">
        <LineChart accessibilityLayer={false} data={data} margin={CHART_MARGIN}>
          <CartesianGrid {...GRID_PROPS} />
          <XAxis dataKey={xKey} {...AXIS_PROPS} />
          <YAxis domain={yDomain} {...AXIS_PROPS} axisLine={false} />
          <Tooltip contentStyle={TOOLTIP_STYLE} />
          {series.length > 1 && <Legend />}
          {series.map((s, i) => (
            <Line
              key={s.key}
              type="monotone"
              dataKey={s.key}
              name={s.label}
              stroke={seriesColor(i)}
              strokeWidth={2.5}
              strokeDasharray={SERIES_DASH[i % SERIES_DASH.length]}
              dot={{ r: 3, fill: seriesColor(i) }}
              activeDot={{ r: 5 }}
              isAnimationActive={false}
            />
          ))}
        </LineChart>
      </ResponsiveContainer>
    </ChartFrame>
  );
}
