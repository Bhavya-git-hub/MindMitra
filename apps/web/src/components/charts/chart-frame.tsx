"use client";

import * as React from "react";

import { cn } from "@/lib/utils";

export interface ChartTable {
  caption: string;
  columns: string[];
  rows: (string | number)[][];
}

/**
 * Accessible wrapper for every chart. The drawing is hidden from assistive technology and a
 * visually hidden table carries the same numbers, so nobody depends on seeing the picture.
 * Never rely on colour alone either: series differ by dash pattern or direct labels.
 */
export function ChartFrame({
  title,
  description,
  table,
  height = 240,
  className,
  children,
}: {
  title: string;
  description?: string;
  table: ChartTable;
  height?: number;
  className?: string;
  children: React.ReactNode;
}) {
  const id = React.useId();
  return (
    <figure className={cn("w-full", className)} aria-labelledby={`${id}-title`}>
      <figcaption id={`${id}-title`} className="mb-3">
        <span className="block text-sm font-medium">{title}</span>
        {description && <span className="block text-sm text-muted-foreground">{description}</span>}
      </figcaption>
      <div aria-hidden="true" style={{ height }} className="w-full min-w-0">
        {children}
      </div>
      <table className="sr-only">
        <caption>{table.caption}</caption>
        <thead>
          <tr>
            {table.columns.map((c) => (
              <th key={c} scope="col">
                {c}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {table.rows.map((row, i) => (
            <tr key={i}>
              {row.map((cell, j) =>
                j === 0 ? (
                  <th key={j} scope="row">
                    {cell}
                  </th>
                ) : (
                  <td key={j}>{cell}</td>
                ),
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </figure>
  );
}

/** Theme-aware colour for the nth series (the palette is contrast-checked in both themes). */
export function seriesColor(index: number): string {
  return `var(--chart-${(index % 5) + 1})`;
}

/** Dash patterns so lines stay distinguishable without colour (WCAG 1.4.1). */
export const SERIES_DASH = [undefined, "6 4", "2 3", "10 3 2 3", "1 4"] as const;

export const AXIS_PROPS = {
  stroke: "var(--muted-foreground)",
  tick: { fill: "var(--muted-foreground)", fontSize: 12 },
  tickLine: false,
} as const;
