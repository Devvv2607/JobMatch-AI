/**
 * The candidate's profile: the form the screens edit (`ProfileDraft`), the record kept in
 * this browser (`StoredProfile`, typed from the API schema so 5c can send it as is), the
 * conversions between them, and the validation messages.
 */
import type { components } from "../api-types";
import { type SalaryCurrency, toUsdPerYear } from "../fx";
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
  /**
   * The minimum salary as the user entered it (LPA or US dollars a year), so the form can
   * show it again. Not sent: the `min_salary_usd` rule holds the converted amount.
   */
  min_salary_input?: { currency: SalaryCurrency; amount: number } | null;
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
  "location",
  "workplace",
  "min_salary_usd",
  "seniority",
  "employment_type",
  "posted_within_days",
  "exclude_industries",
  "exclude_companies",
  "exclude_staffing_agencies",
  "exclude_freelance_gigs",
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
  places: 20,
  placeLength: 100,
  days: 365,
  salary: 10_000_000,
} as const;

/** Every dealbreaker has a draft, on or off, so turning one off keeps what was entered. */
export type RuleDrafts = {
  work_eligibility: { on: boolean; strict: boolean; country: string };
  /** Cities, states or countries, as a posting would write them. */
  location: { on: boolean; strict: boolean; places: string[] };
  workplace: { on: boolean; strict: boolean; allowed: Workplace[] };
  /** `amount` is in LPA for INR, US dollars a year for USD. */
  min_salary_usd: { on: boolean; strict: boolean; amount: string; currency: SalaryCurrency };
  seniority: { on: boolean; strict: boolean; allowed: Seniority[] };
  employment_type: { on: boolean; strict: boolean; allowed: EmploymentType[] };
  exclude_industries: { on: boolean; strict: boolean; industries: string[] };
  exclude_companies: { on: boolean; strict: boolean; companies: string[] };
  startup_backed: { on: boolean; strict: boolean; backers: Backer[] };
  posted_within_days: { on: boolean; strict: boolean; days: string };
  exclude_staffing_agencies: { on: boolean; strict: boolean };
  exclude_freelance_gigs: { on: boolean; strict: boolean };
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
    location: { on: false, strict: false, places: [] },
    workplace: { on: false, strict: false, allowed: [] },
    min_salary_usd: { on: false, strict: false, amount: "", currency: "USD" },
    seniority: { on: false, strict: false, allowed: [] },
    employment_type: { on: false, strict: false, allowed: [] },
    exclude_industries: { on: false, strict: false, industries: [] },
    exclude_companies: { on: false, strict: false, companies: [] },
    startup_backed: { on: false, strict: false, backers: ["yc", "vc"] },
    posted_within_days: { on: false, strict: false, days: "30" },
    exclude_staffing_agencies: { on: false, strict: false },
    exclude_freelance_gigs: { on: false, strict: false },
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
      case "location":
        r.location = { on: true, strict: rule.strict, places: [...rule.places] };
        break;
      case "exclude_staffing_agencies":
      case "exclude_freelance_gigs":
        r[rule.kind] = { on: true, strict: rule.strict };
        break;
      case "workplace":
        r.workplace = { on: true, strict: rule.strict, allowed: [...rule.allowed] };
        break;
      case "min_salary_usd": {
        const typed = stored.min_salary_input;
        // Show what was typed, unless the rule was changed some other way since.
        r.min_salary_usd =
          typed && toUsdPerYear(typed.amount, typed.currency) === rule.amount
            ? { on: true, strict: rule.strict, amount: String(typed.amount), currency: typed.currency }
            : { on: true, strict: rule.strict, amount: String(rule.amount), currency: "USD" };
        break;
      }
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
  // Strict only means something where a posting can leave the answer out.
  const strict = STRICT_APPLIES.has(kind) && rules[kind].strict;
  switch (kind) {
    case "work_eligibility":
      return { kind, strict, country: rules.work_eligibility.country } satisfies RuleOf<typeof kind>;
    case "location":
      return { kind, strict, places: [...rules.location.places] } satisfies RuleOf<typeof kind>;
    case "exclude_staffing_agencies":
    case "exclude_freelance_gigs":
      return { kind, strict } satisfies RuleOf<typeof kind>;
    case "workplace":
      return { kind, strict, allowed: inOrder(rules.workplace.allowed, WORKPLACES) } satisfies RuleOf<typeof kind>;
    case "min_salary_usd":
      return { kind, strict, amount: salaryUsd(rules.min_salary_usd)! } satisfies RuleOf<typeof kind>;
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
    min_salary_input: draft.rules.min_salary_usd.on
      ? {
          currency: draft.rules.min_salary_usd.currency,
          amount: salaryAmount(draft.rules.min_salary_usd)!,
        }
      : null,
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

/**
 * The typed minimum as a number: whole dollars for USD (commas allowed as thousands
 * separators), lakhs with up to two decimals for INR. A comma in an INR amount is refused,
 * because "12,5" could mean 12.5 or 125.
 */
export function salaryAmount(rule: RuleDrafts["min_salary_usd"]): number | null {
  if (rule.currency === "INR" && rule.amount.includes(",")) return null;
  const v = rule.amount.trim().replace(/,/g, "");
  const pattern = rule.currency === "INR" ? /^\d+(\.\d{1,2})?$/ : /^\d+$/;
  return pattern.test(v) ? Number(v) : null;
}

/** The typed minimum in whole US dollars a year, as the API's rule takes it. */
export function salaryUsd(rule: RuleDrafts["min_salary_usd"]): number | null {
  const amount = salaryAmount(rule);
  return amount === null ? null : toUsdPerYear(amount, rule.currency);
}

/** INR when the first country is India, otherwise USD. */
export function defaultSalaryCurrency(countries: readonly string[]): SalaryCurrency {
  return countries[0] === "IN" ? "INR" : "USD";
}

function wholeNumber(value: string): number | null {
  const v = value.trim().replace(/,/g, "");
  return /^\d+$/.test(v) ? Number(v) : null;
}

function validateRules(r: RuleDrafts): Errors {
  const e: Errors = {};
  if (r.work_eligibility.on && !COUNTRIES.has(r.work_eligibility.country))
    e.work_eligibility = "Pick the country you can work from, or turn this off.";
  if (r.location.on) {
    if (r.location.places.length === 0) e.location = "Add at least one city, state or country, or turn this off.";
    else if (r.location.places.length > LIMITS.places) e.location = `Add up to ${LIMITS.places} places.`;
  }
  if (r.workplace.on && r.workplace.allowed.length === 0)
    e.workplace = "Pick at least one kind of workplace, or turn this off.";
  if (r.min_salary_usd.on) {
    const inr = r.min_salary_usd.currency === "INR";
    const usd = salaryUsd(r.min_salary_usd);
    if (usd === null || usd <= 0)
      e.min_salary_usd = inr
        ? "Enter a yearly amount in lakhs, like 8 or 12.5."
        : "Enter a yearly amount in US dollars, like 30000.";
    else if (usd > LIMITS.salary)
      e.min_salary_usd = inr
        ? "That amount looks too high. Enter it in lakhs a year, like 12 for ₹12 LPA."
        : "That amount looks too high. Enter a yearly amount in US dollars.";
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
 * One line per dealbreaker on what "strict" does. Level, employment type, company,
 * staffing agencies and gig work have no "unknown" outcome in rules.py (every job gets a
 * value), so strict would change nothing there: they get no switch, and are always
 * stored with `strict: false`.
 */
export const STRICT_TEXT: Partial<Record<RuleKind, string>> = {
  work_eligibility: "Strict also hides jobs that don’t say where they can be done from.",
  location: "Strict also hides jobs that don’t give a location.",
  workplace: "Strict also hides jobs that don’t say whether they’re remote, hybrid or on-site.",
  min_salary_usd: "Strict also hides jobs that don’t list a salary.",
  posted_within_days: "Strict also hides jobs without a posting date.",
  exclude_industries: "Strict also hides jobs at companies whose industry we don’t know.",
  startup_backed: "Strict shows only companies we know are backed. Off, the rest stay in your list, marked.",
};

export const STRICT_APPLIES: ReadonlySet<RuleKind> = new Set(Object.keys(STRICT_TEXT) as RuleKind[]);

export const RULE_TITLES: Record<RuleKind, string> = {
  work_eligibility: "Where I can legally work",
  location: "Places",
  workplace: "Workplace",
  min_salary_usd: "Minimum salary",
  seniority: "Level",
  employment_type: "Employment type",
  posted_within_days: "Posting age",
  exclude_industries: "Industries to avoid",
  exclude_companies: "Companies to avoid",
  startup_backed: "Startup-backed companies only",
  exclude_staffing_agencies: "No staffing agencies",
  exclude_freelance_gigs: "No freelance or gig work",
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

// ---- Reading back what was stored ---------------------------------------------------

const isObject = (v: unknown): v is Record<string, unknown> => !!v && typeof v === "object" && !Array.isArray(v);

function strings(v: unknown, min: number, max: number, allowed?: readonly string[], maxLength = Infinity): boolean {
  return (
    Array.isArray(v) &&
    v.length >= min &&
    v.length <= max &&
    v.every((x) => typeof x === "string" && x.length > 0 && x.length <= maxLength && (!allowed || allowed.includes(x)))
  );
}

const wholeIn = (v: unknown, lo: number, hi: number) => typeof v === "number" && Number.isInteger(v) && v >= lo && v <= hi;

function isRule(r: unknown): boolean {
  if (!isObject(r) || typeof r.strict !== "boolean") return false;
  switch (r.kind) {
    case "work_eligibility":
      return typeof r.country === "string" && COUNTRIES.has(r.country);
    case "location":
      return strings(r.places, 1, LIMITS.places, undefined, LIMITS.placeLength);
    case "workplace":
      return strings(r.allowed, 1, WORKPLACES.length, WORKPLACES);
    case "min_salary_usd":
      return wholeIn(r.amount, 1, LIMITS.salary);
    case "seniority":
      return strings(r.allowed, 1, ALL_LEVELS.length, ALL_LEVELS);
    case "employment_type":
      return strings(r.allowed, 1, EMPLOYMENT_TYPES.length, EMPLOYMENT_TYPES);
    case "posted_within_days":
      return wholeIn(r.days, 1, LIMITS.days);
    case "exclude_industries":
      return strings(r.industries, 1, LIMITS.industries);
    case "exclude_companies":
      return strings(r.companies, 1, LIMITS.companies);
    case "startup_backed":
      return strings(r.backers, 1, BACKERS.length, BACKERS);
    case "exclude_staffing_agencies":
    case "exclude_freelance_gigs":
      return true;
    default:
      return false; // An unknown kind fails closed.
  }
}

/**
 * Whether a parsed record is a `StoredProfile` all the way down, within the API's limits.
 * Anything else counts as damaged, so no screen ever works from a half-valid record.
 */
export function isStoredProfile(value: unknown): value is StoredProfile {
  if (!isObject(value) || value.version !== 1) return false;
  const { profile, rules, query, updated_at, min_salary_input } = value;
  if (!isObject(profile)) return false;
  if (profile.skills !== undefined && !strings(profile.skills, 0, LIMITS.skills, undefined, LIMITS.skillLength))
    return false;
  const years = profile.years_experience;
  if (years != null && !(typeof years === "number" && Number.isFinite(years) && years >= 0 && years <= LIMITS.years))
    return false;
  const prefs = profile.preferences;
  if (prefs !== undefined) {
    if (!isObject(prefs)) return false;
    if (prefs.workplace !== undefined && !strings(prefs.workplace, 0, WORKPLACES.length, WORKPLACES)) return false;
    if (prefs.countries !== undefined && !strings(prefs.countries, 0, LIMITS.countries, COUNTRY_CODES)) return false;
    if (prefs.seniority !== undefined && !strings(prefs.seniority, 0, ALL_LEVELS.length, ALL_LEVELS)) return false;
  }
  if (!Array.isArray(rules) || !rules.every(isRule)) return false;
  if (!(query === null || (typeof query === "string" && query.length <= 300))) return false;
  if (typeof updated_at !== "string" || Number.isNaN(Date.parse(updated_at))) return false;
  if (min_salary_input != null) {
    if (!isObject(min_salary_input)) return false;
    const { currency, amount } = min_salary_input;
    if (!(currency === "INR" || currency === "USD") || !(typeof amount === "number" && amount > 0)) return false;
  }
  return true;
}

/** The API needs skills or a query to search with (`SearchRequest`), so a profile with neither is not enough. */
export function canSearch(stored: StoredProfile): boolean {
  return (stored.profile.skills?.length ?? 0) > 0 || !!stored.query?.trim();
}
