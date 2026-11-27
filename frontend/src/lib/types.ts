import type { components } from "./api-types";

type Schemas = components["schemas"];

export type SearchResponse = Schemas["SearchResponse"];
export type SearchResult = Schemas["SearchResult"];
export type RuledOut = Schemas["RuledOut"];
export type RuleBreach = Schemas["RuleBreach"];
export type RuleFlag = Schemas["RuleFlag"];
export type JobSummary = Schemas["JobSummary"];
export type Salary = Schemas["Salary"];
export type Explanation = Schemas["Explanation"];
export type ExperienceFit = Schemas["ExperienceFit"];
export type PreferenceMatch = Schemas["PreferenceMatch"];
export type PoolSummary = Schemas["PoolSummary"];
export type ExplanationSentence = Schemas["ExplanationSentence"];
export type SearchProfile = Schemas["SearchProfile"];
export type DealbreakerRule = NonNullable<Schemas["SearchRequest"]["rules"]>[number];
export type RuleKind = DealbreakerRule["kind"];

/**
 * Job fields the card can show that `JobSummary` does not return yet. The database has
 * most of them (or will after Phase 4); 5c adds them to the API. Every field is optional:
 * a card shows a part only when its field is present, and never guesses.
 */
export type JobExtras = {
  description?: string;
  description_quality?: "full" | "snippet";
  eligibility_scope?: "worldwide" | "listed" | "unknown";
  work_countries?: string[];
  poster_type?: "employer" | "staffing_agency";
  engagement_type?: "employee" | "contract" | "gig";
  /** Sources the same posting was seen at, this one included. */
  source_count?: number;
  /** Earlier postings of the same role fingerprint. */
  repost_count?: number;
  logo_url?: string | null;
};

/** The daily list as the screen needs it: the search response plus the extras by job id. */
export type DailyMatches = {
  response: SearchResponse;
  extras: Record<string, JobExtras>;
  /** The optional LLM sentence per job, when it has been fetched. */
  sentences: Record<string, ExplanationSentence>;
  profile: SearchProfile | null;
};

export const DISMISS_REASONS = ["wrong_level", "location", "salary", "company", "other"] as const;
export type DismissReason = (typeof DISMISS_REASONS)[number];

/** Shaped like the `job_feedback` row the personalisation API will take (5c). */
export type JobFeedback = {
  job_id: string;
  action: "saved" | "dismissed";
  reason: DismissReason | null;
  note: string | null;
  created_at: string;
};
