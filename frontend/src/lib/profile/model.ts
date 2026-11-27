/**
 * The candidate's profile: the form the screens edit (`ProfileDraft`), the record kept in
 * this browser (`StoredProfile`, typed from the API schema so 5c can send it as is), the
 * conversions between them, and the validation messages.
 */
import type { components } from "../api-types";
import { COUNTRY_CODES } from "../generated/taxonomy";
import { MAX_SKILLS, MAX_SKILL_LENGTH, collapse } from "../skills";
import type { DealbreakerRule, RuleKind, SearchProfile } from "../types";

type Schemas = components["schemas"];
export type Workplace = NonNullable<Schemas["Preferences"]["workplace"]>[number];
export type Seniority = NonNullable<Schemas["Preferences"]["seniority"]>[number];
export type EmploymentType = Schemas["EmploymentTypeRule"]["allowed"][number];
export type Backer = Schemas["StartupBacked"]["backers"][number];
type RuleOf<K extends RuleKind> = Extract<DealbreakerRule, { kind: K }>;

/**
 * What this browser stores. `profile` and `rules` are exactly the API's `SearchProfile`
 * and `SearchRequest.rules`; `query` is `SearchRequest.query`, where the "field" goes,
 * because the profile schema has no field of its own.
 */
export type StoredProfile = {
  version: 1;
  profile: SearchProfile;
  rules: DealbreakerRule[];
  query: string | null;
  updated_at: string;
};

export const WORKPLACES: readonly Workplace[] = ["remote", "hybrid", "onsite"];
/** The levels onboarding offers; the API accepts more (lead, staff…) for the dealbreaker. */
export const LEVELS: readonly Seniority[] = ["intern", "junior", "mid", "senior"];
export const ALL_LEVELS: readonly Seniority[] = [
  "intern",
  "junior",
  "mid",
  "senior",
  "lead",
  "staff",
  "principal",
  "manager",
  "director",
  "executive",
];
export const EMPLOYMENT_TYPES: readonly EmploymentType[] = ["full_time", "part_time", "contract", "internship"];
export const BACKERS: readonly Backer[] = ["yc", "vc"];

/** The order the dealbreakers appear in, on both screens. */
export const RULE_KINDS: readonly RuleKind[] = [
  "work_eligibility",
  "workplace",
  "min_salary_usd",
  "seniority",
  "employment_type",
  "posted_within_days",
  "exclude_industries",
  "exclude_companies",
  "startup_backed",
];

export const LIMITS = {
  skills: MAX_SKILLS,
  skillLength: MAX_SKILL_LENGTH,
  years: 60,
  field: 100,
  countries: 20,
  industries: 50,
  companies: 200,
  companyLength: 100,
  days: 365,
  salary: 10_000_000,
} as const;

/** Every dealbreaker has a draft, on or off, so turning one off keeps what was entered. */
export type RuleDrafts = {
  work_eligibility: { on: boolean; strict: boolean; country: string };
  workplace: { on: boolean; strict: boolean; allowed: Workplace[] };
  min_salary_usd: { on: boolean; strict: boolean; amount: string };
  seniority: { on: boolean; strict: boolean; allowed: Seniority[] };
  employment_type: { on: boolean; strict: boolean; allowed: EmploymentType[] };
  exclude_industries: { on: boolean; strict: boolean; industries: string[] };
  exclude_companies: { on: boolean; strict: boolean; companies: string[] };
  startup_backed: { on: boolean; strict: boolean; backers: Backer[] };
  posted_within_days: { on: boolean; strict: boolean; days: string };
};

export type ProfileDraft = {
  skills: string[];
  levels: Seniority[];
  /** Kept as typed, so "2.5" and "" survive until validation. */
  years: string;
  field: string;
  countries: string[];
  workplace: Workplace[];
  rules: RuleDrafts;
};

export function emptyRules(): RuleDrafts {
  return {
    work_eligibility: { on: false, strict: false, country: "" },
    workplace: { on: false, strict: false, allowed: [] },
    min_salary_usd: { on: false, strict: false, amount: "" },
    seniority: { on: false, strict: false, allowed: [] },
    employment_type: { on: false, strict: false, allowed: [] },
    exclude_industries: { on: false, strict: false, industries: [] },
    exclude_companies: { on: false, strict: false, companies: [] },
    startup_backed: { on: false, strict: false, backers: ["yc", "vc"] },
    posted_within_days: { on: false, strict: false, days: "30" },
  };
}

export function emptyDraft(): ProfileDraft {
  return { skills: [], levels: [], years: "", field: "", countries: [], workplace: [], rules: emptyRules() };
}

function inOrder<T>(values: readonly T[], order: readonly T[]): T[] {
  return order.filter((v) => values.includes(v));
}

export function draftFromStored(stored: StoredProfile | null): ProfileDraft {
  const draft = emptyDraft();
  if (!stored) return draft;
  const { profile, rules, query } = stored;
  draft.skills = [...(profile.skills ?? [])];
  draft.levels = [...(profile.preferences?.seniority ?? [])];
  draft.years = profile.years_experience == null ? "" : String(profile.years_experience);
  draft.field = query ?? "";
  draft.countries = [...(profile.preferences?.countries ?? [])];
  draft.workplace = [...(profile.preferences?.workplace ?? [])];
  const r = draft.rules;
  for (const rule of rules) {
    switch (rule.kind) {
      case "work_eligibility":
        r.work_eligibility = { on: true, strict: rule.strict, country: rule.country };
        break;
      case "workplace":
        r.workplace = { on: true, strict: rule.strict, allowed: [...rule.allowed] };
        break;
      case "min_salary_usd":
        r.min_salary_usd = { on: true, strict: rule.strict, amount: String(rule.amount) };
        break;
      case "seniority":
        r.seniority = { on: true, strict: rule.strict, allowed: [...rule.allowed] };
        break;
      case "employment_type":
        r.employment_type = { on: true, strict: rule.strict, allowed: [...rule.allowed] };
        break;
      case "exclude_industries":
        r.exclude_industries = { on: true, strict: rule.strict, industries: [...rule.industries] };
        break;
      case "exclude_companies":
        r.exclude_companies = { on: true, strict: rule.strict, companies: [...rule.companies] };
        break;
      case "startup_backed":
        r.startup_backed = { on: true, strict: rule.strict, backers: [...rule.backers] };
        break;
      case "posted_within_days":
        r.posted_within_days = { on: true, strict: rule.strict, days: String(rule.days) };
        break;
    }
  }
  return draft;
}

/** The API rule for one draft, or null when it is off. Call only on a validated draft. */
function ruleFromDraft(kind: RuleKind, rules: RuleDrafts): DealbreakerRule | null {
  if (!rules[kind].on) return null;
  const strict = rules[kind].strict;
  switch (kind) {
    case "work_eligibility":
      return { kind, strict, country: rules.work_eligibility.country } satisfies RuleOf<typeof kind>;
    case "workplace":
      return { kind, strict, allowed: inOrder(rules.workplace.allowed, WORKPLACES) } satisfies RuleOf<typeof kind>;
    case "min_salary_usd":
      return { kind, strict, amount: Number(rules.min_salary_usd.amount) } satisfies RuleOf<typeof kind>;
    case "seniority":
      return { kind, strict, allowed: inOrder(rules.seniority.allowed, ALL_LEVELS) } satisfies RuleOf<typeof kind>;
    case "employment_type":
      return {
        kind,
        strict,
        allowed: inOrder(rules.employment_type.allowed, EMPLOYMENT_TYPES),
      } satisfies RuleOf<typeof kind>;
    case "exclude_industries":
      return { kind, strict, industries: [...rules.exclude_industries.industries] } satisfies RuleOf<typeof kind>;
    case "exclude_companies":
      return { kind, strict, companies: [...rules.exclude_companies.companies] } satisfies RuleOf<typeof kind>;
    case "startup_backed":
      return { kind, strict, backers: inOrder(rules.startup_backed.backers, BACKERS) } satisfies RuleOf<typeof kind>;
    case "posted_within_days":
      return { kind, strict, days: Number(rules.posted_within_days.days) } satisfies RuleOf<typeof kind>;
  }
}

/** Call only on a draft that `validateDraft` passes. */
export function storedFromDraft(draft: ProfileDraft, now: Date = new Date()): StoredProfile {
  const years = draft.years.trim();
  const field = collapse(draft.field);
  return {
    version: 1,
    profile: {
      skills: [...draft.skills],
      years_experience: years === "" ? null : Number(years),
      preferences: {
        workplace: inOrder(draft.workplace, WORKPLACES),
        countries: [...draft.countries],
        seniority: inOrder(draft.levels, ALL_LEVELS),
      },
    },
    rules: RULE_KINDS.map((kind) => ruleFromDraft(kind, draft.rules)).filter((r): r is DealbreakerRule => r !== null),
    query: field || null,
    updated_at: now.toISOString(),
  };
}

// ---- Validation ---------------------------------------------------------------------

/** Field id -> a message that says what to do. Ids name the control the message belongs to. */
export type Errors = Partial<Record<string, string>>;

export type Section = "skills" | "level" | "where" | "dealbreakers";

export const SECTION_FIELDS: Record<Section, readonly string[]> = {
  skills: ["skills"],
  level: ["levels", "years", "field"],
  where: ["countries", "workplace"],
  dealbreakers: RULE_KINDS,
};

const COUNTRIES = new Set(COUNTRY_CODES);

/** `required`: the step's minimum answer is asked for (Next and Save); Skip never asks. */
export function validateSection(section: Section, draft: ProfileDraft, required = true): Errors {
  const errors: Errors = {};
  switch (section) {
    case "skills":
      if (required && draft.skills.length === 0) errors.skills = "Add at least one skill so we can find matches.";
      else if (draft.skills.length > LIMITS.skills)
        errors.skills = `That’s more than ${LIMITS.skills} skills. Remove a few you use least.`;
      break;

    case "level": {
      if (required && draft.levels.length === 0) errors.levels = "Pick at least one level you’d take.";
      const years = draft.years.trim();
      if (years !== "") {
        const n = Number(years);
        if (!/^\d+(\.\d+)?$/.test(years) || Number.isNaN(n))
          errors.years = "Enter your years of experience as a number, like 3 or 1.5.";
        else if (n > LIMITS.years) errors.years = `Enter a number from 0 to ${LIMITS.years}.`;
      }
      if (collapse(draft.field).length > LIMITS.field)
        errors.field = `Keep your field under ${LIMITS.field} characters, like “Data engineering”.`;
      break;
    }

    case "where":
      if (draft.countries.length > LIMITS.countries)
        errors.countries = `Pick up to ${LIMITS.countries} countries.`;
      else if (draft.countries.some((c) => !COUNTRIES.has(c)))
        errors.countries = "One of these countries isn’t one we know yet. Remove it and pick from the list.";
      break;

    case "dealbreakers":
      Object.assign(errors, validateRules(draft.rules));
      break;
  }
  return errors;
}

function wholeNumber(value: string): number | null {
  const v = value.trim().replace(/,/g, "");
  return /^\d+$/.test(v) ? Number(v) : null;
}

function validateRules(r: RuleDrafts): Errors {
  const e: Errors = {};
  if (r.work_eligibility.on && !COUNTRIES.has(r.work_eligibility.country))
    e.work_eligibility = "Pick the country you can work from, or turn this off.";
  if (r.workplace.on && r.workplace.allowed.length === 0)
    e.workplace = "Pick at least one kind of workplace, or turn this off.";
  if (r.min_salary_usd.on) {
    const n = wholeNumber(r.min_salary_usd.amount);
    if (n === null || n <= 0) e.min_salary_usd = "Enter a yearly amount in US dollars, like 30000.";
    else if (n > LIMITS.salary) e.min_salary_usd = "That amount looks too high. Enter a yearly amount in US dollars.";
  }
  if (r.seniority.on && r.seniority.allowed.length === 0)
    e.seniority = "Pick at least one level, or turn this off.";
  if (r.employment_type.on && r.employment_type.allowed.length === 0)
    e.employment_type = "Pick at least one kind of employment, or turn this off.";
  if (r.posted_within_days.on) {
    const n = wholeNumber(r.posted_within_days.days);
    if (n === null || n < 1 || n > LIMITS.days) e.posted_within_days = `Enter a number of days from 1 to ${LIMITS.days}.`;
  }
  if (r.exclude_industries.on && r.exclude_industries.industries.length === 0)
    e.exclude_industries = "Pick at least one industry to avoid, or turn this off.";
  if (r.exclude_companies.on) {
    if (r.exclude_companies.companies.length === 0) e.exclude_companies = "Add at least one company, or turn this off.";
    else if (r.exclude_companies.companies.length > LIMITS.companies)
      e.exclude_companies = `Add up to ${LIMITS.companies} companies.`;
  }
  if (r.startup_backed.on && r.startup_backed.backers.length === 0)
    e.startup_backed = "Pick Y Combinator, a VC firm or both, or turn this off.";
  return e;
}

export function validateDraft(draft: ProfileDraft, required = false): Errors {
  return Object.assign(
    {},
    ...(Object.keys(SECTION_FIELDS) as Section[]).map((s) => validateSection(s, draft, required)),
  ) as Errors;
}

export function hasErrors(errors: Errors): boolean {
  return Object.values(errors).some(Boolean);
}

// ---- Words --------------------------------------------------------------------------

/**
 * One line per dealbreaker on what "strict" does. Rules whose answer every posting
 * gives (level, employment type, company) cannot be "unknown", so strict changes
 * nothing there, and the line says so rather than imply otherwise.
 */
export const STRICT_TEXT: Record<RuleKind, string> = {
  work_eligibility: "Strict also hides jobs that don’t say where they can be done from.",
  workplace: "Strict also hides jobs that don’t say whether they’re remote, hybrid or on-site.",
  min_salary_usd: "Strict also hides jobs that don’t list a salary.",
  seniority: "Every job gets a level, so strict changes nothing here.",
  employment_type: "Every job gets an employment type, so strict changes nothing here.",
  posted_within_days: "Strict also hides jobs without a posting date.",
  exclude_industries: "Strict also hides jobs at companies whose industry we don’t know.",
  exclude_companies: "We always know the company, so strict changes nothing here.",
  startup_backed: "Strict shows only companies we know are backed. Off, the rest stay in your list, marked.",
};

export const RULE_TITLES: Record<RuleKind, string> = {
  work_eligibility: "Where I can legally work",
  workplace: "Workplace",
  min_salary_usd: "Minimum salary",
  seniority: "Level",
  employment_type: "Employment type",
  posted_within_days: "Posting age",
  exclude_industries: "Industries to avoid",
  exclude_companies: "Companies to avoid",
  startup_backed: "Startup-backed companies only",
};

const INDUSTRY_WORDS: Record<string, string> = {
  ai: "AI",
  saas: "SaaS",
  "voice-ai": "Voice AI",
  "hr-tech": "HR tech",
  adtech: "Adtech",
  edtech: "Edtech",
  fintech: "Fintech",
  "e-commerce": "E-commerce",
};

export function industryLabel(tag: string): string {
  return INDUSTRY_WORDS[tag] ?? tag.replace(/-/g, " ").replace(/^\w/, (c) => c.toUpperCase());
}

export const BACKER_LABELS: Record<Backer, string> = { yc: "Y Combinator", vc: "A VC firm" };
