import type { Metadata } from "next";

import { MatchesPage } from "./matches-page";

export const metadata: Metadata = { title: "Today’s matches · JobMatch" };

export default async function Page({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const params = await searchParams;
  const state = typeof params.state === "string" ? params.state : null;
  return <MatchesPage state={state} />;
}
