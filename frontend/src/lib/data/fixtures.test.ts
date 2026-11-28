import { describe, expect, it } from "vitest";

import { check, rulesItemSchema, schemaFor } from "@/test/schema";

import { FIXTURE_PROFILE, FIXTURE_RULES, buildFixtures } from "./fixtures";
import { FixtureSource, STALE_SCENARIO_RULES } from "./source";

const NOW = new Date("2026-11-27T12:00:00Z");
const data = buildFixtures(NOW);
const jobs = [...data.response.results.map((r) => r.job), ...data.response.ruled_out.map((r) => r.job)];
const extras = Object.values(data.extras);
const ageDays = (iso: string | null) => (iso ? (NOW.getTime() - new Date(iso).getTime()) / 86_400_000 : 0);

describe("test data covers the brief's edge cases", () => {
  it("has about 12 postings and at most five matches", () => {
    expect(jobs).toHaveLength(12);
    expect(data.response.results.length).toBeLessThanOrEqual(5);
    expect(new Set(jobs.map((j) => j.id)).size).toBe(12);
  });
  it("covers each posting edge case", () => {
    expect(extras.some((e) => e.description_quality === "snippet")).toBe(true);
    expect(jobs.some((j) => ageDays(j.posted_at) > 90 && ageDays(j.posted_at) < 365)).toBe(true);
    expect(jobs.some((j) => ageDays(j.posted_at) > 365)).toBe(true);
    expect(jobs.some((j) => j.salary.min == null && j.salary.max == null)).toBe(true);
    expect(jobs.some((j) => j.salary.currency === "INR")).toBe(true);
    expect(jobs.some((j) => j.salary.currency === "USD" && j.remote_policy === "remote")).toBe(true);
    expect(jobs.some((j) => j.employment_type === "internship")).toBe(true);
    expect(jobs.some((j) => j.employment_type === "contract")).toBe(true);
    expect(extras.some((e) => e.poster_type === "staffing_agency")).toBe(true);
    expect(extras.some((e) => e.eligibility_scope === "worldwide")).toBe(true);
    expect(extras.some((e) => (e.description?.length ?? 0) > 1000)).toBe(true);
    expect(extras.some((e) => !e.logo_url)).toBe(true);
  });
  it("rules out a job for every dealbreaker kind", () => {
    const kinds = new Set(data.response.ruled_out.flatMap((r) => r.rules.map((b) => b.kind)));
    for (const rule of FIXTURE_RULES) expect(kinds).toContain(rule.kind);
  });
  it("only rules out on unknown for strict rules", () => {
    const strict = new Set(FIXTURE_RULES.filter((r) => r.strict).map((r) => r.kind));
    for (const breach of data.response.ruled_out.flatMap((r) => r.rules)) {
      if (breach.outcome === "unknown") expect(strict).toContain(breach.kind);
    }
  });
  it("the LLM sentence names no skill outside the structured explanation", () => {
    for (const s of Object.values(data.sentences)) {
      if (s.status !== "ok" || !s.sentence) continue;
      const allowed = [...s.explanation.skills.matched, ...s.explanation.skills.missing];
      const named = ["Python", "SQL", "PostgreSQL", "Apache Spark", "Airflow", "AWS", "Kafka", "dbt", "Docker", "Snowflake", "Looker"];
      for (const skill of named) if (s.sentence.includes(skill)) expect(allowed).toContain(skill);
    }
  });
});

describe("test data stays within what the API accepts", () => {
  it("the search request the matches page sends fits SearchRequest", () => {
    const request = { profile: FIXTURE_PROFILE, rules: FIXTURE_RULES, query: null, limit: 5 };
    expect(check(request, schemaFor("SearchRequest"))).toEqual([]);
    for (const rule of FIXTURE_RULES) expect(check(rule, rulesItemSchema())).toEqual([]);
  });

  it("each explanation request fits ExplanationRequest", () => {
    for (const { job } of data.response.results) {
      const request = { job_id: job.id, profile: FIXTURE_PROFILE, rules: FIXTURE_RULES };
      expect(check(request, schemaFor("ExplanationRequest"))).toEqual([]);
    }
  });

  it("the test responses fit SearchResponse and ExplanationSentence", () => {
    expect(check(data.response, schemaFor("SearchResponse"))).toEqual([]);
    for (const sentence of Object.values(data.sentences)) expect(check(sentence, schemaFor("ExplanationSentence"))).toEqual([]);
  });

  it("the stale-posting state fits the API too, and its stale match breaks none of its rules", async () => {
    const stale = await new FixtureSource("stale-posting", 0).dailyMatches({ profile: FIXTURE_PROFILE, rules: [] });
    const request = { profile: FIXTURE_PROFILE, rules: STALE_SCENARIO_RULES, query: null, limit: 5 };
    expect(check(request, schemaFor("SearchRequest"))).toEqual([]);
    expect(check(stale.response, schemaFor("SearchResponse"))).toEqual([]);
    expect(STALE_SCENARIO_RULES.some((r) => r.kind === "posted_within_days")).toBe(false);
    const flagged = stale.response.results.filter((r) => r.job.stale_posting);
    expect(flagged).toHaveLength(1);
    expect(flagged[0]!.rank).toBe(5);
    expect(stale.response.ruled_out.flatMap((r) => r.rules).some((b) => b.kind === "posted_within_days")).toBe(false);
  });

  it("no match breaks the posted-within rule; the stale one is 11 months old", () => {
    const rule = FIXTURE_RULES.find((r) => r.kind === "posted_within_days");
    expect(rule).toMatchObject({ days: 365 });
    const days = rule!.kind === "posted_within_days" ? rule!.days : 0;
    const ages = data.response.results.map((r) => ageDays(r.job.posted_at));
    for (const age of ages) expect(age).toBeLessThanOrEqual(days);
    expect(Math.max(...ages)).toBeGreaterThan(330);
  });
});
