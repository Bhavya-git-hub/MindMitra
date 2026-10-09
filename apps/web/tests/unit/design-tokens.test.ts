import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

const css = readFileSync(path.resolve(import.meta.dirname, "../../src/app/globals.css"), "utf8");

function block(selector: string): Record<string, string> {
  const start = css.indexOf(`${selector} {`);
  expect(start, `${selector} block`).toBeGreaterThan(-1);
  const body = css.slice(start, css.indexOf("\n}", start));
  return Object.fromEntries(
    [...body.matchAll(/--([\w-]+):\s*(#[0-9a-fA-F]{6});/g)].map((m) => [m[1], m[2]]),
  ) as Record<string, string>;
}

function luminance(hex: string): number {
  const channel = (i: number) => {
    const c = parseInt(hex.slice(1 + i * 2, 3 + i * 2), 16) / 255;
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  };
  return 0.2126 * channel(0) + 0.7152 * channel(1) + 0.0722 * channel(2);
}

function ratio(a: string, b: string): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x) as [number, number];
  return (hi + 0.05) / (lo + 0.05);
}

/** [foreground, background] pairs used for text (WCAG 1.4.3: at least 4.5:1). */
const TEXT_PAIRS: [string, string][] = [
  ["foreground", "background"],
  ["card-foreground", "card"],
  ["popover-foreground", "popover"],
  ["primary-foreground", "primary"],
  ["secondary-foreground", "secondary"],
  ["muted-foreground", "background"],
  ["muted-foreground", "muted"],
  ["muted-foreground", "card"],
  ["accent-foreground", "accent"],
  ["destructive-foreground", "destructive"],
  ["destructive", "card"],
  ["destructive", "background"],
  ["primary", "background"],
  ["primary", "card"],
  ["success", "success-soft"],
  ["warning", "warning-soft"],
  ["info", "info-soft"],
  ["sidebar-foreground", "sidebar"],
  ["sidebar-accent-foreground", "sidebar-accent"],
  ["muted-foreground", "sidebar"],
];

/** Boundaries and graphics (WCAG 1.4.11: at least 3:1). */
const NON_TEXT_PAIRS: [string, string][] = [
  ["input", "background"],
  ["input", "card"],
  ["ring", "background"],
  ["ring", "card"],
  ["chart-1", "card"],
  ["chart-2", "card"],
  ["chart-3", "card"],
  ["chart-4", "card"],
  ["chart-5", "card"],
];

describe.each([
  ["light", block(":root")],
  ["dark", block(".dark")],
])("design tokens (%s theme)", (_name, tokens) => {
  it.each(TEXT_PAIRS)("text %s on %s has at least 4.5:1", (fg, bg) => {
    expect(tokens[fg], fg).toBeDefined();
    expect(tokens[bg], bg).toBeDefined();
    expect(ratio(tokens[fg] as string, tokens[bg] as string)).toBeGreaterThanOrEqual(4.5);
  });

  it.each(NON_TEXT_PAIRS)("%s against %s has at least 3:1", (fg, bg) => {
    expect(ratio(tokens[fg] as string, tokens[bg] as string)).toBeGreaterThanOrEqual(3);
  });
});

describe("design tokens", () => {
  it("defines the same tokens in both themes", () => {
    expect(Object.keys(block(".dark")).sort()).toEqual(Object.keys(block(":root")).sort());
  });

  it("honours reduced motion", () => {
    expect(css).toContain("prefers-reduced-motion: reduce");
  });
});
