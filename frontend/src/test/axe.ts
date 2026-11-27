import axe from "axe-core";
import { expect } from "vitest";

/** axe on a rendered container. jsdom has no layout, so colour contrast is checked
 * separately (by hand and in the screenshots), not here. */
export async function expectNoAxeViolations(container: Element) {
  const result = await axe.run(container, { rules: { "color-contrast": { enabled: false } } });
  const summary = result.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).join(", ")}`);
  expect(summary).toEqual([]);
}
