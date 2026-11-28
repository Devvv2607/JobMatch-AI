/**
 * Test data for 5a. Every company, posting and person here is made up; nothing is copied
 * from the job snapshot. Shapes are the API's own types, so a drift fails the typecheck.
 *
 * Edge cases covered (see docs/briefs/phase-5.md): short source snippet, postings over
 * 90 and over 365 days old, no salary, INR salary, USD remote, internship, staffing
 * agency, contract, worldwide eligibility, a ruled-out job for every dealbreaker kind,
 * a long description, and a missing company logo.
 */
import type {
  DailyMatches,
  DealbreakerRule,
  Explanation,
  ExplanationSentence,
  JobExtras,
  JobSummary,
  RuledOut,
  SearchProfile,
  SearchResponse,
  SearchResult,
} from "../types";

const DAY_MS = 24 * 60 * 60 * 1000;

function daysAgo(days: number, now: Date): string {
  return new Date(now.getTime() - days * DAY_MS).toISOString();
}

export const FIXTURE_PROFILE: SearchProfile = {
  skills: ["Python", "SQL", "PostgreSQL", "Apache Spark", "Airflow", "AWS", "dbt", "Docker"],
  years_experience: 3,
  preferences: {
    workplace: ["remote", "hybrid"],
    countries: ["IN"],
    seniority: ["junior", "mid"],
  },
};

export const FIXTURE_RULES: DealbreakerRule[] = [
  { kind: "work_eligibility", country: "IN", strict: true },
  { kind: "workplace", allowed: ["remote", "hybrid"], strict: false },
  { kind: "min_salary_usd", amount: 15000, strict: false },
  { kind: "seniority", allowed: ["intern", "junior", "mid"], strict: false },
  { kind: "employment_type", allowed: ["full_time", "contract", "internship"], strict: false },
  { kind: "exclude_industries", industries: ["fintech", "gambling"], strict: false },
  { kind: "exclude_companies", companies: ["Vantage Dynamics"], strict: false },
  { kind: "startup_backed", backers: ["yc", "vc"], strict: true },
  { kind: "posted_within_days", days: 365, strict: false },
];

type JobSeed = Omit<JobSummary, "posted_at" | "first_seen_at" | "status" | "source_url"> & {
  postedDaysAgo: number | null;
};

function job(seed: JobSeed, now: Date): JobSummary {
  const { postedDaysAgo, ...rest } = seed;
  return {
    ...rest,
    posted_at: postedDaysAgo == null ? null : daysAgo(postedDaysAgo, now),
    first_seen_at: daysAgo(Math.max(0, (postedDaysAgo ?? 3) - 1), now),
    status: "live",
    source_url: `https://jobs.example.com/${rest.id}`,
  };
}

const NO_SALARY = { min: null, max: null, currency: null, interval: null, min_usd: null, max_usd: null };

const LONG_DESCRIPTION = `Kestrel Analytics builds forecasting tools for regional grocery chains. Our data platform ingests point-of-sale feeds from about 1,400 stores every night and turns them into demand forecasts that store managers read the next morning.

You will join a team of five data engineers in Bengaluru. Most of our pipelines run on Apache Spark and are orchestrated with Airflow on AWS. We are moving the busiest feeds from nightly batches to streaming with Kafka this year, and you will help design that move.

What you will do
- Own three to four ingestion pipelines end to end: schemas, tests, alerts and the runbook.
- Profile and tune Spark jobs; last quarter the team cut the nightly run from 3 hours to 70 minutes.
- Work with the forecasting team on feature tables and their freshness guarantees.
- Review pull requests and pair with the two junior engineers on the team.

What we look for
- Two or more years building data pipelines in Python and SQL.
- Hands-on Spark experience, including reading a query plan.
- Comfort with AWS (S3, EMR or Glue, IAM basics).
- Kafka or another message broker is a plus, not a requirement; we will teach it.

How we work
Hybrid: two days a week in our Indiranagar office, the rest from home. Core hours are 11:00 to 16:00 IST. We publish salary ranges on every posting and do not negotiate them down.

Interview process: a 30-minute call with the hiring manager, a take-home pipeline exercise (paid, about three hours), and a final conversation with two engineers from the team. We reply to every applicant within ten working days.`;

function explanation(e: Partial<Explanation> & Pick<Explanation, "skills" | "experience">): Explanation {
  return { preferences: [], flags: [], ...e };
}

function scores(rank: number) {
  return {
    final: 0.9 - rank * 0.06,
    rerank_logit: 2.1 - rank * 0.4,
    rrf: 0.03 - rank * 0.002,
    components: { rerank: 0.8 - rank * 0.05, skills: 0.7, experience: 1, preferences: 0.8 },
    ranks: { bm25: rank + 1, vector: rank + 2, fused: rank },
  };
}

const PREF_WORKPLACE = (job: string, match: boolean | null) => ({
  name: "workplace" as const,
  wanted: ["remote", "hybrid"],
  job: [job],
  match,
});
const PREF_COUNTRY = (job: string[], match: boolean | null) => ({
  name: "countries" as const,
  wanted: ["IN"],
  job,
  match,
});
const PREF_LEVEL = (job: string, match: boolean) => ({
  name: "seniority" as const,
  wanted: ["junior", "mid"],
  job: [job],
  match,
});

export function buildFixtures(now: Date = new Date()): DailyMatches {
  const results: SearchResult[] = [];
  const extras: Record<string, JobExtras> = {};
  const sentences: Record<string, ExplanationSentence> = {};

  // 1. Long description, INR annual salary, hybrid, has a logo, LLM sentence ok.
  const kestrel = job(
    {
      id: "0b6f6c1e-5a43-4c1e-9b0e-1d2a3c4b5e01",
      title: "Data Engineer",
      company: "Kestrel Analytics",
      location: "Bengaluru, India",
      remote_policy: "hybrid",
      seniority: "mid",
      employment_type: "full_time",
      salary: { min: 1_800_000, max: 2_400_000, currency: "INR", interval: "year", min_usd: 21_600, max_usd: 28_800 },
      skills: ["Python", "SQL", "Apache Spark", "Airflow", "AWS", "Kafka"],
      source: "greenhouse",
      postedDaysAgo: 6,
    },
    now,
  );
  results.push({
    rank: 1,
    job: kestrel,
    scores: scores(1),
    explanation: explanation({
      skills: { matched: ["Python", "SQL", "Apache Spark", "Airflow", "AWS"], missing: ["Kafka"], coverage: 5 / 6 },
      experience: { seniority: "mid", expected_years: [2, 5], candidate_years: 3, fit: "within" },
      preferences: [PREF_WORKPLACE("hybrid", true), PREF_COUNTRY(["IN"], true), PREF_LEVEL("mid", true)],
    }),
  });
  extras[kestrel.id] = {
    description: LONG_DESCRIPTION,
    description_quality: "full",
    eligibility_scope: "listed",
    work_countries: ["IN"],
    poster_type: "employer",
    engagement_type: "employee",
    source_count: 1,
    repost_count: 0,
    logo_url: "/fixtures/logos/kestrel.svg",
  };
  sentences[kestrel.id] = {
    job_id: kestrel.id,
    explanation: results[0]!.explanation,
    sentence:
      "Your Apache Spark, Airflow and AWS work covers most of this role; Kafka is the one listed skill you would need to pick up.",
    status: "ok",
    detail: null,
    quota_remaining: 41,
  };

  // 2. USD remote, worldwide eligibility, over 90 days old, missing logo, industry unknown flag.
  const tallgrass = job(
    {
      id: "0b6f6c1e-5a43-4c1e-9b0e-1d2a3c4b5e02",
      title: "Backend Engineer, Data APIs",
      company: "Tallgrass Labs",
      location: "Remote",
      remote_policy: "remote",
      seniority: "mid",
      employment_type: "full_time",
      salary: { min: 140_000, max: 170_000, currency: "USD", interval: "year", min_usd: 140_000, max_usd: 170_000 },
      skills: ["Python", "PostgreSQL", "FastAPI", "Docker", "Kubernetes"],
      source: "ashby",
      postedDaysAgo: 125,
    },
    now,
  );
  results.push({
    rank: 2,
    job: tallgrass,
    scores: scores(2),
    explanation: explanation({
      skills: { matched: ["Python", "PostgreSQL", "Docker"], missing: ["FastAPI", "Kubernetes"], coverage: 3 / 5 },
      experience: { seniority: "mid", expected_years: [2, 5], candidate_years: 3, fit: "within" },
      preferences: [PREF_WORKPLACE("remote", true), PREF_COUNTRY(["worldwide"], true), PREF_LEVEL("mid", true)],
      flags: [{ kind: "exclude_industries", rule: "Not in: fintech, gambling", reason: "Company industry unknown" }],
    }),
  });
  extras[tallgrass.id] = {
    description:
      "Tallgrass Labs makes an open-source time-series store used by weather and agriculture researchers. You will build and run the public query API (Python, FastAPI, PostgreSQL) and its client libraries. We are fully remote and hire anywhere; you will overlap at least three hours a day with 14:00–17:00 UTC.",
    description_quality: "full",
    eligibility_scope: "worldwide",
    poster_type: "employer",
    engagement_type: "employee",
    source_count: 1,
    repost_count: 0,
    logo_url: null,
  };
  sentences[tallgrass.id] = {
    job_id: tallgrass.id,
    explanation: results[1]!.explanation,
    sentence: null,
    status: "dropped",
    detail: "named a skill not in the explanation",
    quota_remaining: 41,
  };

  // 3. Adzuna-style snippet, staffing agency, contract, no salary, over 365 days, reposted.
  const brightwater = job(
    {
      id: "0b6f6c1e-5a43-4c1e-9b0e-1d2a3c4b5e03",
      title: "Data Platform Engineer (12-month contract)",
      company: "Brightwater Talent Partners",
      location: "Remote, India",
      remote_policy: "remote",
      seniority: "mid",
      employment_type: "contract",
      salary: NO_SALARY,
      skills: ["Python", "SQL", "Snowflake"],
      source: "adzuna",
      postedDaysAgo: 340,
    },
    now,
  );
  results.push({
    rank: 3,
    job: brightwater,
    scores: scores(3),
    explanation: explanation({
      skills: { matched: ["Python", "SQL"], missing: ["Snowflake"], coverage: 2 / 3 },
      experience: { seniority: "mid", expected_years: [2, 5], candidate_years: 3, fit: "within" },
      preferences: [PREF_WORKPLACE("remote", true), PREF_COUNTRY(["IN"], true), PREF_LEVEL("mid", true)],
      flags: [{ kind: "min_salary_usd", rule: "Salary at least USD 15,000 a year", reason: "Salary not listed" }],
    }),
  });
  extras[brightwater.id] = {
    description:
      "Our client, a leading retail group, is looking for a Data Platform Engineer to join on a 12-month contract. You will build and maintain pipelines in Python and SQL and help migrate reporting to Snowflake. Immediate joiners preferred…",
    description_quality: "snippet",
    eligibility_scope: "listed",
    work_countries: ["IN"],
    poster_type: "staffing_agency",
    engagement_type: "contract",
    source_count: 2,
    repost_count: 3,
    logo_url: null,
  };

  // 4. Internship with a monthly INR stipend; pitched below the candidate's experience.
  const pinecrest = job(
    {
      id: "0b6f6c1e-5a43-4c1e-9b0e-1d2a3c4b5e04",
      title: "Data Engineering Intern",
      company: "Pinecrest Mobility",
      location: "Pune, India",
      remote_policy: "hybrid",
      seniority: "intern",
      employment_type: "internship",
      salary: { min: 40_000, max: 40_000, currency: "INR", interval: "month", min_usd: 5_760, max_usd: 5_760 },
      skills: ["Python", "SQL", "Airflow"],
      source: "lever",
      postedDaysAgo: 12,
    },
    now,
  );
  results.push({
    rank: 4,
    job: pinecrest,
    scores: scores(4),
    explanation: explanation({
      skills: { matched: ["Python", "SQL", "Airflow"], missing: [], coverage: 1 },
      experience: { seniority: "intern", expected_years: [0, 1], candidate_years: 3, fit: "above" },
      preferences: [PREF_WORKPLACE("hybrid", true), PREF_COUNTRY(["IN"], true), PREF_LEVEL("intern", false)],
    }),
  });
  extras[pinecrest.id] = {
    description:
      "A six-month internship on the trip-data team at Pinecrest Mobility, an electric-bus operator in Pune. You will clean GPS and ticketing data with Python and SQL and help move our nightly jobs to Airflow. Two days a week in the Baner depot office.",
    description_quality: "full",
    eligibility_scope: "listed",
    work_countries: ["IN"],
    poster_type: "employer",
    engagement_type: "employee",
    source_count: 1,
    repost_count: 0,
    logo_url: "/fixtures/logos/pinecrest.svg",
  };
  sentences[pinecrest.id] = {
    job_id: pinecrest.id,
    explanation: results[3]!.explanation,
    sentence: null,
    status: "unavailable",
    detail: "daily quota reached",
    quota_remaining: 0,
  };

  // 5. Upper bound only, remote India, about a month old, no sentence fetched.
  const juniper = job(
    {
      id: "0b6f6c1e-5a43-4c1e-9b0e-1d2a3c4b5e05",
      title: "Analytics Engineer",
      company: "Juniper Health",
      location: "Remote, India",
      remote_policy: "remote",
      seniority: "mid",
      employment_type: "full_time",
      salary: { min: null, max: 3_000_000, currency: "INR", interval: "year", min_usd: null, max_usd: 36_000 },
      skills: ["SQL", "dbt", "Python", "Looker"],
      source: "himalayas",
      postedDaysAgo: 40,
    },
    now,
  );
  results.push({
    rank: 5,
    job: juniper,
    scores: scores(5),
    explanation: explanation({
      skills: { matched: ["SQL", "dbt", "Python"], missing: ["Looker"], coverage: 3 / 4 },
      experience: { seniority: "mid", expected_years: [2, 5], candidate_years: 3, fit: "within" },
      preferences: [PREF_WORKPLACE("remote", true), PREF_COUNTRY(["IN"], true), PREF_LEVEL("mid", true)],
    }),
  });
  extras[juniper.id] = {
    description:
      "Juniper Health runs telehealth clinics in four Indian states. As our second analytics engineer you will own the dbt project that turns appointment and prescription data into the tables our clinicians and finance team use every day.",
    description_quality: "full",
    eligibility_scope: "listed",
    work_countries: ["IN"],
    poster_type: "employer",
    engagement_type: "employee",
    source_count: 1,
    repost_count: 0,
    logo_url: null,
  };

  const ruled_out: RuledOut[] = [
    {
      job: job(
        {
          id: "0b6f6c1e-5a43-4c1e-9b0e-1d2a3c4b5e06",
          title: "Senior Data Engineer",
          company: "Copperline Freight",
          location: "Hyderabad, India",
          remote_policy: "hybrid",
          seniority: "senior",
          employment_type: "full_time",
          salary: { min: 3_500_000, max: 4_500_000, currency: "INR", interval: "year", min_usd: 42_000, max_usd: 54_000 },
          skills: ["Python", "Apache Spark", "AWS"],
          source: "greenhouse",
          postedDaysAgo: 9,
        },
        now,
      ),
      rules: [{ kind: "seniority", rule: "Level: intern, junior, mid", outcome: "violates", reason: null }],
    },
    {
      job: job(
        {
          id: "0b6f6c1e-5a43-4c1e-9b0e-1d2a3c4b5e07",
          title: "ML Platform Engineer",
          company: "Halden Systems",
          location: "Berlin, Germany",
          remote_policy: "onsite",
          seniority: "mid",
          employment_type: "full_time",
          salary: { min: 70_000, max: 85_000, currency: "EUR", interval: "year", min_usd: 75_600, max_usd: 91_800 },
          skills: ["Python", "Kubernetes", "AWS"],
          source: "ashby",
          postedDaysAgo: 20,
        },
        now,
      ),
      rules: [
        { kind: "work_eligibility", rule: "Open to candidates in IN", outcome: "violates", reason: null },
        { kind: "workplace", rule: "Workplace: remote or hybrid", outcome: "violates", reason: null },
      ],
    },
    {
      job: job(
        {
          id: "0b6f6c1e-5a43-4c1e-9b0e-1d2a3c4b5e08",
          title: "Data Engineer, Payments",
          company: "Orbitpay",
          location: "Remote, India",
          remote_policy: "remote",
          seniority: "mid",
          employment_type: "full_time",
          salary: { min: 2_000_000, max: 2_600_000, currency: "INR", interval: "year", min_usd: 24_000, max_usd: 31_200 },
          skills: ["Python", "SQL", "Kafka"],
          source: "lever",
          postedDaysAgo: 15,
        },
        now,
      ),
      rules: [{ kind: "exclude_industries", rule: "Not in: fintech, gambling", outcome: "violates", reason: null }],
    },
    {
      job: job(
        {
          id: "0b6f6c1e-5a43-4c1e-9b0e-1d2a3c4b5e09",
          title: "Junior Data Analyst",
          company: "Ferncastle Retail",
          location: "Chennai, India",
          remote_policy: "hybrid",
          seniority: "junior",
          employment_type: "full_time",
          salary: { min: 500_000, max: 700_000, currency: "INR", interval: "year", min_usd: 6_000, max_usd: 8_400 },
          skills: ["SQL", "Excel"],
          source: "smartrecruiters",
          postedDaysAgo: 30,
        },
        now,
      ),
      rules: [{ kind: "min_salary_usd", rule: "Salary at least USD 15,000 a year", outcome: "violates", reason: null }],
    },
    {
      job: job(
        {
          id: "0b6f6c1e-5a43-4c1e-9b0e-1d2a3c4b5e10",
          title: "Data Engineer (part-time, 20 h/week)",
          company: "Quillfeather Books",
          location: "Remote, India",
          remote_policy: "remote",
          seniority: "mid",
          employment_type: "part_time",
          salary: NO_SALARY,
          skills: ["Python", "PostgreSQL"],
          source: "himalayas",
          postedDaysAgo: 4,
        },
        now,
      ),
      rules: [{ kind: "employment_type", rule: "Employment: full_time, contract, internship", outcome: "violates", reason: null }],
    },
    {
      job: job(
        {
          id: "0b6f6c1e-5a43-4c1e-9b0e-1d2a3c4b5e11",
          title: "Data Engineer II",
          company: "Vantage Dynamics",
          location: "Bengaluru, India",
          remote_policy: "hybrid",
          seniority: "mid",
          employment_type: "full_time",
          salary: { min: 2_200_000, max: 2_800_000, currency: "INR", interval: "year", min_usd: 26_400, max_usd: 33_600 },
          skills: ["Python", "SQL", "Apache Spark"],
          source: "greenhouse",
          postedDaysAgo: 2,
        },
        now,
      ),
      rules: [{ kind: "exclude_companies", rule: "Not at: Vantage Dynamics", outcome: "violates", reason: null }],
    },
    {
      job: job(
        {
          id: "0b6f6c1e-5a43-4c1e-9b0e-1d2a3c4b5e12",
          title: "Big Data Developer",
          company: "Lumenfield Software",
          location: "Remote",
          remote_policy: "remote",
          seniority: "mid",
          employment_type: "full_time",
          salary: NO_SALARY,
          skills: ["Hadoop", "Apache Spark", "Scala"],
          source: "adzuna",
          postedDaysAgo: 790,
        },
        now,
      ),
      rules: [
        { kind: "posted_within_days", rule: "Posted in the last 365 days", outcome: "violates", reason: null },
        {
          kind: "work_eligibility",
          rule: "Open to candidates in IN",
          outcome: "unknown",
          reason: "The posting does not say where the job can be done from",
        },
        { kind: "startup_backed", rule: "Backed by Y Combinator or a VC firm", outcome: "unknown", reason: "Not known to be startup-backed" },
      ],
    },
  ];

  const response: SearchResponse = {
    query: "Python SQL PostgreSQL Apache Spark Airflow AWS dbt Docker",
    results,
    ruled_out,
    pool: {
      pool: 23_705,
      allowed: 9_412,
      ruled_out_by_rule: { work_eligibility: 11_204, workplace: 1_380, seniority: 1_102, posted_within_days: 607 },
      flagged_by_rule: { min_salary_usd: 6_850, exclude_industries: 4_120 },
      eligibility: null,
      updated_at: new Date(now.getTime() - 3 * 60 * 60 * 1000).toISOString(),
    },
    bm25_version: "fixture",
    rerank_profile: "interactive",
    reranked: 10,
    degraded: [],
    timings_ms: {},
    cached: false,
  };

  return { response, extras, sentences, profile: FIXTURE_PROFILE };
}
