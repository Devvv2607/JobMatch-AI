"use client";

import { useMemo } from "react";

import { MatchesScreen } from "@/components/matches/matches-screen";
import { defaultSource, toScenario } from "@/lib/data/source";

export function MatchesPage({ state }: { state: string | null }) {
  const scenario = toScenario(state);
  const source = useMemo(() => defaultSource(scenario), [scenario]);
  return <MatchesScreen key={scenario} source={source} scenario={scenario} />;
}
