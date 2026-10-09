import axe from "axe-core";
import { expect } from "vitest";

/**
 * Runs axe-core (WCAG 2.0/2.1 A and AA) on a rendered tree. jsdom has no layout engine, so
 * colour contrast is covered separately by design-tokens.test.ts and the Playwright run.
 */
export async function expectNoA11yViolations(container: Element) {
  const results = await axe.run(container, {
    runOnly: { type: "tag", values: ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"] },
    rules: { "color-contrast": { enabled: false }, region: { enabled: false } },
  });
  const summary = results.violations.map(
    (v) => `${v.id}: ${v.help}\n${v.nodes.map((n) => `  ${n.html}`).join("\n")}`,
  );
  expect(summary, summary.join("\n")).toEqual([]);
}
