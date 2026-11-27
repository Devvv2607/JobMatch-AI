import { describe, expect, it } from "vitest";

import { FIXTURE_RULES, buildFixtures } from "./fixtures";

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
