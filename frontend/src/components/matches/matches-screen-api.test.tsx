import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { buildFixtures } from "@/lib/data/fixtures";
import type { MatchesRequest, MatchesSource } from "@/lib/data/source";
import type { StoredProfile } from "@/lib/profile/model";
import { writeProfile } from "@/lib/profile/store";

import { MatchesScreen } from "./matches-screen";

vi.mock("@/lib/auth", () => ({ useAuth: () => ({ state: { status: "signed-in", accessToken: "t" } }) }));

function apiSource() {
  const calls: MatchesRequest[] = [];
  const source: MatchesSource = {
    kind: "api",
    dailyMatches: async (request) => {
      calls.push(request);
      return buildFixtures();
    },
  };
  return { source, calls };
}

describe("MatchesScreen against the API", () => {
  it("asks for a profile, and doesn't search, when this browser has none", () => {
    const { source, calls } = apiSource();
    render(<MatchesScreen source={source} scenario="default" />);
    expect(screen.getByRole("heading", { name: /Tell us what you’re looking for/ })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Set up your profile" })).toHaveAttribute("href", "/onboarding");
    expect(calls).toHaveLength(0);
  });

  it("searches with the profile, rules and field kept in this browser", async () => {
    const saved: StoredProfile = {
      version: 1,
      profile: { skills: ["Rust"], years_experience: 4, preferences: { workplace: ["remote"], countries: [], seniority: [] } },
      rules: [{ kind: "workplace", allowed: ["remote"], strict: true }],
      query: "Systems programming",
      updated_at: "2026-11-28T00:00:00.000Z",
    };
    writeProfile(saved);
    const { source, calls } = apiSource();
    render(<MatchesScreen source={source} scenario="default" />);
    await screen.findByRole("region", { name: "5 matches" });
    expect(calls).toEqual([{ profile: saved.profile, rules: saved.rules, query: "Systems programming", accessToken: "t" }]);
  });
});
