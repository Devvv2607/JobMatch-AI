import { ApiError, api, networkError, toApiError } from "../api";
import type { DailyMatches, DealbreakerRule, ExplanationSentence, SearchProfile, SearchResponse } from "../types";
import { FIXTURE_PROFILE, FIXTURE_RULES, buildFixtures } from "./fixtures";

/** The states a reviewer can ask the test data for (`/matches?state=…`). */
export const SCENARIOS = [
  "default",
  "loading",
  "no-profile",
  "no-matches",
  "all-ruled-out",
  "degraded",
  "error-network",
  "error-auth",
  "error-rate-limit",
] as const;
export type Scenario = (typeof SCENARIOS)[number];

export function toScenario(value: string | null): Scenario {
  return (SCENARIOS as readonly string[]).includes(value ?? "") ? (value as Scenario) : "default";
}

export type MatchesRequest = {
  profile: SearchProfile | null;
  rules: DealbreakerRule[];
  accessToken?: string | null;
};

/** Where the daily list comes from. 5a ships `fixtures`; `api` is wired for 5c. */
export interface MatchesSource {
  readonly kind: "fixtures" | "api";
  dailyMatches(request: MatchesRequest, signal?: AbortSignal): Promise<DailyMatches>;
}

export class FixtureSource implements MatchesSource {
  readonly kind = "fixtures";

  constructor(
    private readonly scenario: Scenario = "default",
    private readonly delayMs = 450,
  ) {}

  async dailyMatches(_request: MatchesRequest, signal?: AbortSignal): Promise<DailyMatches> {
    if (this.scenario === "loading") return new Promise(() => {});
    await new Promise((resolve) => setTimeout(resolve, this.delayMs));
    if (signal?.aborted) throw new DOMException("aborted", "AbortError");

    const data = buildFixtures();
    switch (this.scenario) {
      case "no-profile":
        return { ...data, profile: null, response: { ...data.response, results: [], ruled_out: [] } };
      case "no-matches":
        return { ...data, response: { ...data.response, results: [], ruled_out: [] } };
      case "all-ruled-out":
        return { ...data, response: { ...data.response, results: [] } };
      case "degraded":
        return { ...data, response: { ...data.response, degraded: ["rerank_unavailable"] } };
      case "error-network":
        throw networkError();
      case "error-auth":
        throw new ApiError("Your session has ended. Sign in again.", 401, "unauthorized");
      case "error-rate-limit":
        throw new ApiError("Too many searches. Try again in 30 seconds.", 429, "rate_limited");
      default:
        return data;
    }
  }
}

/** Calls the real API. Not the default until 5c stores the profile server-side. */
export class ApiSource implements MatchesSource {
  readonly kind = "api";

  async dailyMatches({ profile, rules, accessToken }: MatchesRequest, signal?: AbortSignal): Promise<DailyMatches> {
    const headers = accessToken ? { Authorization: `Bearer ${accessToken}` } : undefined;
    let result;
    try {
      result = await api.POST("/api/v1/search", {
        body: { profile, rules, limit: 5 },
        headers,
        signal,
      });
    } catch (error) {
      if ((error as Error).name === "AbortError") throw error;
      throw networkError();
    }
    if (!result.data) throw toApiError(result.error, result.response);
    // openapi-fetch widens the `expected_years` tuple to number[]; the schema is a pair.
    const response = result.data as SearchResponse;

    // The LLM sentence is optional: fetch it per job, keep whatever arrives.
    const sentences: Record<string, ExplanationSentence> = {};
    await Promise.all(
      response.results.map(async ({ job }) => {
        try {
          const r = await api.POST("/api/v1/search/explanation", {
            body: { job_id: job.id, profile, rules },
            headers,
            signal,
          });
          if (r.data) sentences[job.id] = r.data as ExplanationSentence;
        } catch {
          // No sentence is a complete card.
        }
      }),
    );
    return { response, extras: {}, sentences, profile };
  }
}

export function defaultSource(scenario: Scenario): MatchesSource {
  return process.env.NEXT_PUBLIC_DATA_SOURCE === "api" ? new ApiSource() : new FixtureSource(scenario);
}

export { FIXTURE_PROFILE, FIXTURE_RULES };
