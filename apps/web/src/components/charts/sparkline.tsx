"use client";

import { Area, AreaChart, ResponsiveContainer } from "recharts";

import { seriesColor } from "./chart-frame";

/** A tiny trend line for stat cards. Decorative: the card's text carries the meaning. */
export function Sparkline({ values, index = 0 }: { values: number[]; index?: number }) {
  const data = values.map((value, i) => ({ i, value }));
  const color = seriesColor(index);
  return (
    <div aria-hidden="true" className="h-10 w-24 shrink-0">
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart
          accessibilityLayer={false}
          data={data}
          margin={{ top: 2, right: 0, bottom: 2, left: 0 }}
        >
          <Area
            type="monotone"
            dataKey="value"
            stroke={color}
            strokeWidth={2}
            fill={color}
            fillOpacity={0.15}
            isAnimationActive={false}
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}
