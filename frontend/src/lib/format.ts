import type { ExperienceFit, PreferenceMatch, RuleBreach, Salary } from "./types";

const DAY_MS = 24 * 60 * 60 * 1000;

/** "Posted today", "Posted 6 days ago", "Posted 4 months ago", "Posted 14 months ago".
 * Months up to two years, so a stale posting reads as precisely as the backlog asks. */
export function postedAge(postedAt: string | null, now: Date = new Date()): string | null {
  if (!postedAt) return null;
  const days = Math.floor((now.getTime() - new Date(postedAt).getTime()) / DAY_MS);
  if (Number.isNaN(days)) return null;
  if (days <= 0) return "Posted today";
  if (days === 1) return "Posted yesterday";
  if (days < 30) return `Posted ${days} days ago`;
  const months = Math.floor(days / 30.44);
  if (months < 2) return "Posted 1 month ago";
  if (months < 24) return `Posted ${months} months ago`;
  return `Posted ${Math.floor(months / 12)} years ago`;
}

const INTERVAL_WORDS: Record<string, string> = {
  year: "a year",
  month: "a month",
  week: "a week",
  day: "a day",
  hour: "an hour",
};

function money(amount: number, currency: string): string {
  return new Intl.NumberFormat(currency === "INR" ? "en-IN" : "en-US", {
    style: "currency",
    currency,
    maximumFractionDigits: 0,
  }).format(amount);
}

function lakh(amount: number): string {
  const value = amount / 100_000;
  return Number.isInteger(value) ? String(value) : value.toFixed(1).replace(/\.0$/, "");
}

/**
 * The salary as the posting states it, in its own currency and interval. Annual INR in
 * whole lakhs reads as LPA, the way Indian postings say it. The USD conversion is never
 * the headline.
 */
export function formatSalary(salary: Salary): string {
  const { min, max, currency, interval } = salary;
  if (min == null && max == null) return "Salary not stated";
  if (!currency) return "Salary stated without a currency";

  if (currency === "INR" && interval === "year" && (min ?? max ?? 0) >= 100_000) {
    if (min != null && max != null && min !== max) return `₹${lakh(min)}–${lakh(max)} LPA`;
    if (min != null && max == null) return `From ₹${lakh(min)} LPA`;
    if (min == null && max != null) return `Up to ₹${lakh(max)} LPA`;
    return `₹${lakh((min ?? max) as number)} LPA`;
  }

  const per = interval ? ` ${INTERVAL_WORDS[interval] ?? `per ${interval}`}` : "";
  if (min != null && max != null && min !== max) return `${money(min, currency)}–${money(max, currency)}${per}`;
  if (min != null && max == null) return `From ${money(min, currency)}${per}`;
  if (min == null && max != null) return `Up to ${money(max, currency)}${per}`;
  return `${money((min ?? max) as number, currency)}${per}`;
}

const WORDS: Record<string, string> = {
  remote: "Remote",
  hybrid: "Hybrid",
  onsite: "On-site",
  unknown: "Workplace not stated",
  full_time: "Full-time",
  part_time: "Part-time",
  contract: "Contract",
  internship: "Internship",
  temporary: "Temporary",
  intern: "Intern",
  junior: "Junior",
  mid: "Mid-level",
  senior: "Senior",
  lead: "Lead",
  staff: "Staff",
  principal: "Principal",
  manager: "Manager",
  director: "Director",
  executive: "Executive",
};

export function label(value: string): string {
  return WORDS[value] ?? value.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());
}

function years(n: number): string {
  return `${Number.isInteger(n) ? n : n.toFixed(1)} ${n === 1 ? "year" : "years"}`;
}

function range([lo, hi]: [number, number]): string {
  return lo === hi ? years(lo) : `${lo}–${years(hi)}`;
}

/** One sentence about experience fit, or null when there is nothing to say. */
export function experienceText(fit: ExperienceFit): { text: string; good: boolean } | null {
  const level = label(fit.seniority);
  const you = fit.candidate_years;
  const want = fit.expected_years;
  switch (fit.fit) {
    case "within":
      return {
        good: true,
        text:
          you != null && want
            ? `Your ${years(you)} fit the ${range(want)} a ${level.toLowerCase()} role usually asks for`
            : `Your experience fits a ${level.toLowerCase()} role`,
      };
    case "below":
      return {
        good: false,
        text:
          you != null && want
            ? `${level} roles usually ask for ${range(want)}; you have ${years(you)}`
            : `${level} roles usually ask for more experience than you list`,
      };
    case "above":
      return {
        good: false,
        text:
          you != null && want
            ? `Pitched below your experience: ${range(want)} expected, you have ${years(you)}`
            : "Pitched below your experience",
      };
    default:
      return null;
  }
}

const PREF_NAMES: Record<PreferenceMatch["name"], string> = {
  workplace: "Workplace",
  countries: "Location",
  seniority: "Level",
};

const REGIONS = new Intl.DisplayNames(["en"], { type: "region" });

export function country(code: string): string {
  if (code === "worldwide") return "Worldwide";
  try {
    return REGIONS.of(code.toUpperCase()) ?? code;
  } catch {
    return code;
  }
}

function list(values: string[], name: PreferenceMatch["name"]): string {
  return values.map(name === "countries" ? country : label).join(" or ");
}

/** A preference line for "why it matches" (match true) or "gaps" (false or unknown). */
export function preferenceText(pref: PreferenceMatch): string {
  const name = PREF_NAMES[pref.name];
  const job = list(pref.job, pref.name);
  const wanted = list(pref.wanted, pref.name);
  if (pref.match === true) return `${name}: ${job}, as you prefer`;
  if (pref.match === false) return `${name}: ${job}; you prefer ${wanted}`;
  return `${name}: the posting doesn't say (you prefer ${wanted})`;
}

export function breachText(breach: RuleBreach): { lead: string; detail: string | null } {
  // The backend's rule text uses enum values ("full_time"); show them as words.
  const rule = breach.rule.replace(/\b([a-z]+)_([a-z]+)\b/g, "$1-$2");
  if (breach.outcome === "violates") return { lead: `Breaks “${rule}”`, detail: null };
  return { lead: `Couldn't check “${rule}”`, detail: breach.reason };
}

export function relativeUpdated(updatedAt: string | null, now: Date = new Date()): string | null {
  if (!updatedAt) return null;
  const minutes = Math.round((now.getTime() - new Date(updatedAt).getTime()) / 60_000);
  if (minutes < 1) return "updated just now";
  if (minutes < 60) return `updated ${minutes} ${minutes === 1 ? "minute" : "minutes"} ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 48) return `updated ${hours} ${hours === 1 ? "hour" : "hours"} ago`;
  return `updated ${Math.round(hours / 24)} days ago`;
}

export const NUMBER = new Intl.NumberFormat("en-US");

const SOURCE_NAMES: Record<string, string> = {
  greenhouse: "Greenhouse",
  lever: "Lever",
  ashby: "Ashby",
  smartrecruiters: "SmartRecruiters",
  himalayas: "Himalayas",
  adzuna: "Adzuna",
  remotive: "Remotive",
};

export function sourceName(source: string): string {
  return SOURCE_NAMES[source] ?? label(source);
}
