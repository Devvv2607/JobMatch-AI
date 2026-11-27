import { expect } from "vitest";

/**
 * jsdom has no layout, so 360 px is checked by rule instead: nothing in the tree may set a
 * fixed width or min-width wider than the 328 px a 360 px screen leaves inside its 16 px
 * gutters, at the base (mobile) breakpoint. Breakpoint-prefixed classes (sm:, md:) and
 * max-width caps are fine. Screenshots confirm it in a real browser.
 */
const GUTTERED = 360 - 2 * 16;
const REM = 16;

function px(value: string): number | null {
  const unit = /^(\d+(?:\.\d+)?)(px|rem)$/.exec(value);
  if (unit) return Number(unit[1]) * (unit[2] === "rem" ? REM : 1);
  if (/^\d+(\.\d+)?$/.test(value)) return Number(value) * 4; // Tailwind spacing scale
  return null;
}

export function expectFitsNarrowScreen(container: Element) {
  const offenders: string[] = [];
  for (const el of container.querySelectorAll<HTMLElement>("[class]")) {
    for (const cls of el.className.toString().split(/\s+/)) {
      const m = /^(?:min-)?w-(?:\[(.+)\]|(\d+(?:\.\d+)?))$/.exec(cls);
      if (!m) continue;
      const width = px(m[1] ?? m[2]!);
      if (width !== null && width > GUTTERED) offenders.push(`${el.tagName.toLowerCase()}.${cls}`);
    }
    if (el.style.width && (px(el.style.width) ?? 0) > GUTTERED) offenders.push(`${el.tagName.toLowerCase()} style`);
  }
  expect(offenders).toEqual([]);
}
