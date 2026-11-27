import { describe, expect, it } from "vitest";

import { breachText, experienceText, formatSalary, postedAge, preferenceText } from "./format";

const NOW = new Date("2026-11-27T12:00:00Z");
const ago = (days: number) => new Date(NOW.getTime() - days * 86_400_000).toISOString();
const salary = (min: number | null, max: number | null, currency: string | null, interval: string | null) => ({
  min,
  max,
  currency,
  interval,
  min_usd: null,
  max_usd: null,
});

describe("formatSalary", () => {
  it("says when no salary is stated", () => {
    expect(formatSalary(salary(null, null, null, null))).toBe("Salary not stated");
  });
  it("shows annual INR as LPA in the original currency", () => {
    expect(formatSalary(salary(1_800_000, 2_400_000, "INR", "year"))).toBe("₹18–24 LPA");
    expect(formatSalary(salary(null, 3_000_000, "INR", "year"))).toBe("Up to ₹30 LPA");
    expect(formatSalary(salary(1_250_000, null, "INR", "year"))).toBe("From ₹12.5 LPA");
  });
  it("shows a monthly INR stipend per month with Indian grouping", () => {
    expect(formatSalary(salary(40_000, 40_000, "INR", "month"))).toBe("₹40,000 a month");
  });
  it("shows USD and EUR ranges with the interval", () => {
    expect(formatSalary(salary(140_000, 170_000, "USD", "year"))).toBe("$140,000–$170,000 a year");
    expect(formatSalary(salary(70_000, 85_000, "EUR", "year"))).toBe("€70,000–€85,000 a year");
  });
});

describe("postedAge", () => {
  it("counts days, then months up to two years", () => {
    expect(postedAge(ago(0), NOW)).toBe("Posted today");
    expect(postedAge(ago(6), NOW)).toBe("Posted 6 days ago");
    expect(postedAge(ago(125), NOW)).toBe("Posted 4 months ago");
    expect(postedAge(ago(430), NOW)).toBe("Posted 14 months ago");
    expect(postedAge(ago(790), NOW)).toBe("Posted 2 years ago");
  });
  it("returns null without a date", () => {
    expect(postedAge(null, NOW)).toBeNull();
  });
});

describe("explanation text", () => {
  it("describes experience fit from the structured fields only", () => {
    expect(experienceText({ seniority: "mid", expected_years: [2, 5], candidate_years: 3, fit: "within" })).toEqual({
      good: true,
      text: "Your 3 years fit the 2–5 years a mid-level role usually asks for",
    });
    expect(experienceText({ seniority: "intern", expected_years: [0, 1], candidate_years: 3, fit: "above" })?.good).toBe(false);
    expect(experienceText({ seniority: "mid", expected_years: null, candidate_years: null, fit: "unknown" })).toBeNull();
  });
  it("names countries and says when the posting is silent", () => {
    expect(preferenceText({ name: "countries", wanted: ["IN"], job: ["IN"], match: true })).toBe("Location: India, as you prefer");
    expect(preferenceText({ name: "workplace", wanted: ["remote"], job: ["unknown"], match: null })).toBe(
      "Workplace: the posting doesn't say (you prefer Remote)",
    );
  });
  it("words rule breaches and turns enum values into words", () => {
    expect(breachText({ kind: "employment_type", rule: "Employment: full_time, contract", outcome: "violates", reason: null })).toEqual({
      lead: "Breaks “Employment: full-time, contract”",
      detail: null,
    });
    expect(breachText({ kind: "min_salary_usd", rule: "Salary at least USD 15,000 a year", outcome: "unknown", reason: "Salary not listed" }).detail).toBe(
      "Salary not listed",
    );
  });
});
