import { SKILLS, SKILL_ALIASES } from "./generated/taxonomy";

/** The backend's limits on a candidate skill (SearchProfile._bounded). */
export const MAX_SKILLS = 100;
export const MAX_SKILL_LENGTH = 64;

/** Whitespace collapsed, as the backend's `" ".join(value.split())`. */
export function collapse(value: string): string {
  return value.split(/\s+/).filter(Boolean).join(" ");
}

/**
 * The name to store for what the user typed: the canonical taxonomy name for a known
 * skill or alias ("postgres" -> "PostgreSQL"), otherwise the text as typed with spaces
 * collapsed. The same mapping as the backend's canonical_skill(), so what is stored here
 * compares equal to the posting's skills there.
 */
export function canonicalSkill(value: string): string {
  const typed = collapse(value);
  return SKILL_ALIASES[typed.toLowerCase()] ?? typed;
}

/** Up to `limit` taxonomy skills for an autocomplete, best first; skips ones already chosen. */
export function suggestSkills(query: string, chosen: readonly string[], limit = 8): string[] {
  const q = collapse(query).toLowerCase();
  if (!q) return [];
  const taken = new Set(chosen.map((s) => s.toLowerCase()));
  const scored = new Map<string, number>();
  const consider = (name: string, key: string) => {
    if (taken.has(name.toLowerCase())) return;
    const at = key.indexOf(q);
    if (at < 0) return;
    // Name prefix beats alias prefix beats a match inside a word.
    const score = (at === 0 ? 0 : 2) + (key === name.toLowerCase() ? 0 : 1);
    const best = scored.get(name);
    if (best === undefined || score < best) scored.set(name, score);
  };
  for (const name of SKILLS) consider(name, name.toLowerCase());
  for (const [alias, name] of Object.entries(SKILL_ALIASES)) consider(name, alias);
  return [...scored.entries()]
    .sort((a, b) => a[1] - b[1] || SKILLS.indexOf(a[0]) - SKILLS.indexOf(b[0]))
    .slice(0, limit)
    .map(([name]) => name);
}
