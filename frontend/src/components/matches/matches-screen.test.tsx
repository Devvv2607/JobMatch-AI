import { render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { FixtureSource, type Scenario } from "@/lib/data/source";
import { expectNoAxeViolations } from "@/test/axe";

import { MatchesScreen } from "./matches-screen";

vi.mock("@/lib/auth", () => ({ useAuth: () => ({ state: { status: "signed-out" } }) }));

function renderScenario(scenario: Scenario) {
  return render(<MatchesScreen source={new FixtureSource(scenario, 0)} scenario={scenario} />);
}

describe("MatchesScreen with test data", () => {
  it("lists at most five matches, then the ruled-out jobs with their rules", async () => {
    const { container } = renderScenario("default");
    const matches = await screen.findByRole("region", { name: "5 matches" });
    expect(within(matches).getAllByRole("article")).toHaveLength(5);
    expect(screen.getByRole("heading", { name: "Ruled out today" })).toBeInTheDocument();
    expect(screen.getByText("Breaks “Not at: Vantage Dynamics”")).toBeInTheDocument();
    expect(screen.getAllByText(/^Couldn't check/)).toHaveLength(2);
    expect(screen.getByText(/Searched 23,705 postings · updated 3 hours ago/)).toBeInTheDocument();
    expect(screen.getByText(/Test data/)).toBeInTheDocument();
    // Only a one-line summary is live, not the list itself.
    expect(screen.getByText("5 matches today, 8 ruled out.")).toHaveAttribute("aria-live", "polite");
    expect(matches.closest("[aria-live]")).toBeNull();
    await expectNoAxeViolations(container);
  });

  it("shows a loading state with a status message", async () => {
    const { container } = renderScenario("loading");
    expect(screen.getByRole("status")).toHaveTextContent("Finding today’s matches");
    expect(container.querySelector("[aria-busy='true']")).not.toBeNull();
    await expectNoAxeViolations(container);
  });

  it.each<[Scenario, RegExp]>([
    ["no-profile", /Tell us what you’re looking for/],
    ["no-matches", /No new matches today/],
    ["all-ruled-out", /Nothing passed your dealbreakers today/],
  ])("empty state %s", async (scenario, heading) => {
    const { container } = renderScenario(scenario);
    expect(await screen.findByRole("heading", { name: heading })).toBeInTheDocument();
    await expectNoAxeViolations(container);
  });

  it.each<[Scenario, RegExp, string]>([
    ["error-network", /Can’t reach JobMatch/, "Try again"],
    ["error-rate-limit", /Too many searches/, "Try again"],
    ["error-auth", /Your session has ended/, "Sign in"],
  ])("error state %s", async (scenario, heading, action) => {
    const { container } = renderScenario(scenario);
    const alert = await screen.findByRole("alert");
    expect(within(alert).getByRole("heading", { name: heading })).toBeInTheDocument();
    expect(within(alert).getByText(action)).toBeInTheDocument();
    await expectNoAxeViolations(container);
  });

  it("stale-posting state: the stale match comes last with the API's note", async () => {
    const { container } = renderScenario("stale-posting");
    const matches = await screen.findByRole("region", { name: "5 matches" });
    const cards = within(matches).getAllByRole("article");
    expect(cards[4]).toHaveTextContent("Brightwater Talent Partners");
    expect(cards[4]).toHaveTextContent("Old posting: posted over a year ago");
    expect(screen.getAllByText(/Old posting/)).toHaveLength(1);
    // The ruled-out list takes a stale posting's age from the API's note too.
    expect(screen.getByText("Posted over a year ago")).toBeInTheDocument();
    expect(screen.queryByText(/Posted 2 years ago/)).toBeNull();
    await expectNoAxeViolations(container);
  });

  it("says quietly when a stage was skipped", async () => {
    renderScenario("degraded");
    expect(await screen.findByText(/relevance re-check was skipped/)).toBeInTheDocument();
  });
});
