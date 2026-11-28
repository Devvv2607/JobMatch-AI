import { describe, expect, it } from "vitest";

import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { check, rulesItemSchema, schemaFor } from "@/test/schema";

import { INR_PER_USD, toUsdPerYear } from "../fx";

import type { DealbreakerRule, RuleKind } from "../types";
import {
  RULE_KINDS,
  STRICT_APPLIES,
  STRICT_TEXT,
  defaultSalaryCurrency,
  draftFromStored,
  emptyDraft,
  storedFromDraft,
  validateDraft,
  validateSection,
  type ProfileDraft,
  type StoredProfile,
} from "./model";
import { PROFILE_KEY, readProfile, writeProfile } from "./store";

/** One rule of every kind, as the API takes them. */
function everyRule(strict: boolean): DealbreakerRule[] {
  return [
    { kind: "work_eligibility", country: "IN", strict },
    { kind: "location", places: ["Bengaluru", "Pune"], strict },
    { kind: "workplace", allowed: ["remote", "hybrid"], strict },
    { kind: "min_salary_usd", amount: 20000, strict },
    { kind: "seniority", allowed: ["junior", "mid"], strict },
    { kind: "employment_type", allowed: ["full_time", "contract"], strict },
    { kind: "posted_within_days", days: 60, strict },
    { kind: "exclude_industries", industries: ["crypto", "adtech"], strict },
    { kind: "exclude_companies", companies: ["Vantage Dynamics", "Orbitpay"], strict },
    { kind: "exclude_staffing_agencies", strict },
    { kind: "exclude_freelance_gigs", strict },
    { kind: "startup_backed", backers: ["yc"], strict },
  ];
}

function filledDraft(): ProfileDraft {
  const draft = emptyDraft();
  draft.skills = ["Python", "PostgreSQL", "Some in-house tool"];
  draft.levels = ["mid", "junior"];
  draft.years = "2.5";
  draft.field = "  Data   engineering ";
  draft.countries = ["IN", "DE"];
  draft.workplace = ["hybrid", "remote"];
  return draft;
}

const stored = (rules: DealbreakerRule[]): StoredProfile => ({
  version: 1,
  profile: { skills: ["Python"], years_experience: 3, preferences: { workplace: [], countries: [], seniority: [] } },
  rules,
  query: null,
  updated_at: "2026-11-28T10:00:00.000Z",
});

describe("every dealbreaker round-trips through storage with its strict flag", () => {
  it.each(RULE_KINDS.map((kind) => [kind]))("%s", (kind: RuleKind) => {
    for (const strict of [true, false]) {
      const rule = everyRule(strict).find((r) => r.kind === kind)!;
      // Strict is kept where it means something; elsewhere it is always stored off.
      const expected = { ...rule, strict: STRICT_APPLIES.has(kind) && strict };
      // Through the form and back...
      const draft = draftFromStored(stored([rule]));
      expect(draft.rules[kind]).toMatchObject({ on: true });
      const again = storedFromDraft(draft);
      expect(again.rules).toEqual([expected]);
      // ...and through localStorage, twice.
      expect(writeProfile(again)).toBe(true);
      const read = readProfile();
      expect(read.status).toBe("ready");
      expect(read.status === "ready" && read.stored.rules).toEqual([expected]);
      expect(read.status === "ready" && storedFromDraft(draftFromStored(read.stored)).rules).toEqual([expected]);
    }
  });

  it("all twelve together, in a fixed order, and a rule turned off keeps its values but isn't stored", () => {
    const draft = draftFromStored(stored(everyRule(true)));
    expect(storedFromDraft(draft).rules.map((r) => r.kind)).toEqual(RULE_KINDS);
    draft.rules.min_salary_usd.on = false;
    const out = storedFromDraft(draft);
    expect(out.rules.map((r) => r.kind)).not.toContain("min_salary_usd");
    expect(draft.rules.min_salary_usd.amount).toBe("20000");
  });
});

describe("stored data matches the API schema", () => {
  it("profile, rules and query fit SearchProfile, SearchRequest.rules and SearchRequest.query", () => {
    const draft = filledDraft();
    draft.rules = draftFromStored(stored(everyRule(true))).rules;
    expect(validateDraft(draft, true)).toEqual({});
    const out = storedFromDraft(draft);

    expect(check(out.profile, schemaFor("SearchProfile"))).toEqual([]);
    for (const rule of out.rules) expect(check(rule, rulesItemSchema())).toEqual([]);
    const query = (schemaFor("SearchRequest").properties as Record<string, Record<string, unknown>>).query!;
    expect(check(out.query, query)).toEqual([]);

    // A whole search request built from it is valid too (what 5c will send).
    expect(check({ profile: out.profile, rules: out.rules, query: out.query, limit: 5 }, schemaFor("SearchRequest"))).toEqual(
      [],
    );
    expect(out.profile).toEqual({
      skills: ["Python", "PostgreSQL", "Some in-house tool"],
      years_experience: 2.5,
      preferences: { workplace: ["remote", "hybrid"], countries: ["IN", "DE"], seniority: ["junior", "mid"] },
    });
    expect(out.query).toBe("Data engineering");
  });

  it("an empty profile (every step skipped) is valid too", () => {
    const out = storedFromDraft(emptyDraft());
    expect(check(out.profile, schemaFor("SearchProfile"))).toEqual([]);
    expect(out.rules).toEqual([]);
    expect(out.query).toBeNull();
  });

  it("the checker does catch a bad value", () => {
    expect(check({ skills: "Python" }, schemaFor("SearchProfile"))).not.toEqual([]);
    expect(check({ kind: "posted_within_days", days: 400, strict: false }, rulesItemSchema())).not.toEqual([]);
    expect(check({ kind: "workplace", allowed: ["office"], strict: false }, rulesItemSchema())).not.toEqual([]);
  });
});

describe("validation messages", () => {
  it("say what to do, in words", () => {
    const draft = emptyDraft();
    expect(validateSection("skills", draft)).toEqual({ skills: "Add at least one skill so we can find matches." });
    expect(validateSection("skills", draft, false)).toEqual({});

    draft.years = "three";
    expect(validateSection("level", draft, false).years).toBe("Enter your years of experience as a number, like 3 or 1.5.");
    draft.years = "75";
    expect(validateSection("level", draft, false).years).toBe("Enter a number from 0 to 60.");

    for (const kind of RULE_KINDS) draft.rules[kind].on = true;
    draft.rules.startup_backed.backers = [];
    draft.rules.posted_within_days.days = "0";
    const errors = validateSection("dealbreakers", draft);
    // The two on/off rules have nothing to fill in, so nothing to get wrong.
    const withValues = RULE_KINDS.filter((k) => k !== "exclude_staffing_agencies" && k !== "exclude_freelance_gigs");
    expect(Object.keys(errors).sort()).toEqual([...withValues].sort());
    const all = Object.values(validateDraft(draft)).join(" ");
    expect(all).not.toMatch(/invalid/i);
    expect(errors.posted_within_days).toBe("Enter a number of days from 1 to 365.");
    expect(errors.min_salary_usd).toBe("Enter a yearly amount in US dollars, like 30000.");
  });

  it("strict is offered, with one line, only where a posting can leave the answer out", () => {
    expect([...STRICT_APPLIES].sort()).toEqual(
      [
        "exclude_industries",
        "location",
        "min_salary_usd",
        "posted_within_days",
        "startup_backed",
        "work_eligibility",
        "workplace",
      ],
    );
    for (const kind of STRICT_APPLIES) {
      const text = STRICT_TEXT[kind]!;
      expect(text).toMatch(/^[A-Z].+\.$/);
      expect(text.split(". ").length).toBeLessThanOrEqual(2);
    }
  });
});

describe("storage", () => {
  it("reports damaged data instead of guessing", () => {
    window.localStorage.setItem(PROFILE_KEY, "{not json");
    expect(readProfile()).toEqual({ status: "error", reason: "damaged" });
    window.localStorage.setItem(PROFILE_KEY, JSON.stringify({ version: 9 }));
    expect(readProfile()).toEqual({ status: "error", reason: "damaged" });
    window.localStorage.removeItem(PROFILE_KEY);
    expect(readProfile()).toEqual({ status: "empty" });
  });
});

describe("minimum salary in INR (LPA) or USD", () => {
  function salaryDraft(amount: string, currency: "INR" | "USD") {
    const draft = emptyDraft();
    draft.rules.min_salary_usd = { on: true, strict: false, amount, currency };
    return draft;
  }

  it("uses the backend's own INR rate, as of its date", () => {
    const table = readFileSync(resolve(__dirname, "../../../../backend/app/ingest/data/fx_rates.yaml"), "utf8");
    const perEur = (code: string) => Number(new RegExp(`^  ${code}: ([0-9.]+)`, "m").exec(table)![1]);
    expect(INR_PER_USD.rate).toBeCloseTo(perEur("INR") / perEur("USD"), 2);
    expect(table).toContain(`date: "${INR_PER_USD.asOf}"`);
  });

  it("converts LPA to whole US dollars a year for the API, and keeps what was typed", () => {
    expect(toUsdPerYear(8, "INR")).toBe(Math.round(800_000 / INR_PER_USD.rate));
    expect(toUsdPerYear(8, "INR")).toBe(8517);
    expect(toUsdPerYear(12.5, "INR")).toBe(13308);
    const out = storedFromDraft(salaryDraft("12.5", "INR"));
    expect(out.rules).toEqual([{ kind: "min_salary_usd", amount: 13308, strict: false }]);
    expect(out.min_salary_input).toEqual({ currency: "INR", amount: 12.5 });
    expect(check(out.rules[0], rulesItemSchema())).toEqual([]);
    expect(draftFromStored(out).rules.min_salary_usd).toMatchObject({ amount: "12.5", currency: "INR" });
  });

  it("sends USD as typed", () => {
    const out = storedFromDraft(salaryDraft("30,000", "USD"));
    expect(out.rules).toEqual([{ kind: "min_salary_usd", amount: 30000, strict: false }]);
    expect(out.min_salary_input).toEqual({ currency: "USD", amount: 30000 });
    expect(draftFromStored(out).rules.min_salary_usd).toMatchObject({ amount: "30000", currency: "USD" });
  });

  it("falls back to USD when the stored rule no longer matches what was typed", () => {
    const out = storedFromDraft(salaryDraft("8", "INR"));
    out.rules = [{ kind: "min_salary_usd", amount: 9000, strict: false }];
    expect(draftFromStored(out).rules.min_salary_usd).toMatchObject({ amount: "9000", currency: "USD" });
  });

  it("asks for the amount in the unit chosen", () => {
    expect(validateSection("dealbreakers", salaryDraft("eight", "INR")).min_salary_usd).toBe(
      "Enter a yearly amount in lakhs, like 8 or 12.5.",
    );
    expect(validateSection("dealbreakers", salaryDraft("8.125", "INR")).min_salary_usd).toBe(
      "Enter a yearly amount in lakhs, like 8 or 12.5.",
    );
    expect(validateSection("dealbreakers", salaryDraft("12.5", "USD")).min_salary_usd).toBe(
      "Enter a yearly amount in US dollars, like 30000.",
    );
    expect(validateSection("dealbreakers", salaryDraft("2500000", "INR")).min_salary_usd).toMatch(/lakhs a year/);
    expect(validateSection("dealbreakers", salaryDraft("8", "INR"))).toEqual({});
  });

  it("defaults to the currency of the first country", () => {
    expect(defaultSalaryCurrency(["IN", "US"])).toBe("INR");
    expect(defaultSalaryCurrency(["US", "IN"])).toBe("USD");
    expect(defaultSalaryCurrency([])).toBe("USD");
  });
});
