"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";

import { Button } from "@/components/button";
import { SiteHeader } from "@/components/site-header";
import { ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import {
  FIXTURE_PROFILE,
  FIXTURE_RULES,
  SCENARIOS,
  type MatchesRequest,
  type MatchesSource,
  type Scenario,
} from "@/lib/data/source";
import { NUMBER, relativeUpdated } from "@/lib/format";
import { canSearch } from "@/lib/profile/model";
import { useStoredProfile } from "@/lib/profile/store";
import type { DailyMatches } from "@/lib/types";

import { MatchCard } from "./match-card";
import { RuledOutList } from "./ruled-out-list";

type State =
  | { status: "loading" }
  | { status: "ready"; data: DailyMatches }
  | { status: "error"; error: ApiError };

const DATE = new Intl.DateTimeFormat("en-GB", { weekday: "long", day: "numeric", month: "long" });

const DEGRADED_NOTES: Record<string, string> = {
  rerank_unavailable: "the relevance re-check was skipped, so the order may be rougher than usual",
  bm25_unavailable: "keyword search was unavailable, so matches come from meaning alone",
  vector_unavailable: "meaning-based search was unavailable, so matches come from keywords alone",
};

type Request = Omit<MatchesRequest, "accessToken">;

function useDailyMatches(source: MatchesSource, request: Request | null, accessToken: string | null, enabled: boolean) {
  const [state, setState] = useState<State>({ status: "loading" });
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    if (!enabled || !request) return;
    const controller = new AbortController();
    source
      .dailyMatches({ ...request, accessToken }, controller.signal)
      .then((data) => setState({ status: "ready", data }))
      .catch((error: unknown) => {
        if ((error as Error).name === "AbortError") return;
        setState({
          status: "error",
          error: error instanceof ApiError ? error : new ApiError("Something went wrong.", 0, "unknown"),
        });
      });
    return () => controller.abort();
  }, [source, request, accessToken, enabled, attempt]);

  const retry = useCallback(() => {
    setState({ status: "loading" });
    setAttempt((n) => n + 1);
  }, []);

  return { state, retry };
}

export function MatchesScreen({ source, scenario }: { source: MatchesSource; scenario: Scenario }) {
  const usesApi = source.kind === "api";
  const { state: auth } = useAuth();
  const router = useRouter();
  const accessToken = auth.status === "signed-in" ? auth.accessToken : null;
  const enabled = !usesApi || auth.status === "signed-in";
  const stored = useStoredProfile();

  // Test data searches with the test profile. The API searches with the profile kept in
  // this browser, and without one there is nothing to search with yet.
  const request = useMemo<Request | null>(() => {
    if (!usesApi) return { profile: FIXTURE_PROFILE, rules: FIXTURE_RULES, query: null };
    // A profile with no skills and no field (every onboarding step skipped) gives the API
    // nothing to search with: it would answer 422, so treat it as no profile.
    if (stored?.status !== "ready" || !canSearch(stored.stored)) return null;
    const { profile, rules, query } = stored.stored;
    return { profile, rules, query };
  }, [usesApi, stored]);
  const noProfile = usesApi && stored !== null && request === null;
  const { state, retry } = useDailyMatches(source, request, accessToken, enabled);

  useEffect(() => {
    if (usesApi && auth.status === "signed-out") router.replace("/login");
  }, [usesApi, auth.status, router]);

  useEffect(() => {
    if (state.status === "error" && state.error.status === 401 && usesApi) router.replace("/login");
  }, [state, usesApi, router]);

  const today = useMemo(() => DATE.format(new Date()), []);

  return (
    <div className="min-h-dvh">
      <SiteHeader current="matches" skipLabel="Skip to matches" />

      <main id="main" className="mx-auto w-full max-w-4xl px-4 pt-10 pb-20 sm:px-6 sm:pt-14">
        {!usesApi && (
          <p className="mb-8 inline-block rounded-sm border border-rule bg-surface px-3 py-1.5 text-sm text-muted">
            Test data: made-up postings. Nothing is sent anywhere.
          </p>
        )}

        <h1 className="font-serif text-4xl leading-tight font-medium tracking-tight sm:text-5xl">Today’s matches</h1>
        <Subtitle today={today} state={state} />

        {/* One short live line, not the whole list, so a screen reader doesn't read five cards on load. */}
        <p className="sr-only" aria-live="polite">
          {!noProfile && state.status === "ready" ? loadedText(state.data) : ""}
        </p>
        <div aria-busy={!noProfile && state.status === "loading"} className="mt-8">
          {noProfile ? (
            <NoProfile />
          ) : (
            <>
              {state.status === "loading" && <Loading />}
              {state.status === "error" && <ErrorState error={state.error} onRetry={retry} />}
              {state.status === "ready" && <Ready data={state.data} />}
            </>
          )}
        </div>

        {!usesApi && <ScenarioNav current={scenario} />}
      </main>
    </div>
  );
}

function Subtitle({ today, state }: { today: string; state: State }) {
  if (state.status !== "ready" || !state.data.profile) {
    return <p className="mt-3 text-muted">{today}</p>;
  }
  const { pool } = state.data.response;
  const updated = relativeUpdated(pool.updated_at);
  return (
    <p className="mt-3 text-muted">
      {today} · Searched {NUMBER.format(pool.pool)} postings{updated ? ` · ${updated}` : ""}
    </p>
  );
}

function Ready({ data }: { data: DailyMatches }) {
  const { response, extras, sentences, profile } = data;
  const { results, ruled_out, degraded } = response;

  if (!profile) return <NoProfile />;

  return (
    <>
      {degraded.length > 0 && (
        <p className="mb-6 border-l-2 border-rule pl-3 text-sm text-muted">
          Today {degraded.map((d) => DEGRADED_NOTES[d] ?? `${d.replace(/_/g, " ")}`).join("; ")}.
        </p>
      )}

      {results.length > 0 ? (
        <section aria-labelledby="matches-heading">
          <h2 id="matches-heading" className="sr-only">
            {results.length} {results.length === 1 ? "match" : "matches"}
          </h2>
          <ol className="border-b border-rule">
            {results.map((result) => (
              <li key={result.job.id}>
                <MatchCard result={result} extras={extras[result.job.id]} sentence={sentences[result.job.id]} />
              </li>
            ))}
          </ol>
        </section>
      ) : ruled_out.length > 0 ? (
        <EmptyState title="Nothing passed your dealbreakers today">
          <p>
            {ruled_out.length} {ruled_out.length === 1 ? "posting" : "postings"} fit your skills but broke a
            dealbreaker. They’re listed below with the rule, in case one is worth loosening.
          </p>
        </EmptyState>
      ) : (
        <EmptyState title="No new matches today">
          <p>
            Nothing new fits your skills and dealbreakers today. New postings arrive every morning, and we’d rather show
            you nothing than five weak matches.
          </p>
        </EmptyState>
      )}

      {ruled_out.length > 0 && (
        <details open className="group mt-14">
          <summary className="flex min-h-11 cursor-pointer list-none items-baseline gap-3 [&::-webkit-details-marker]:hidden">
            <h2 className="font-serif text-2xl font-medium">Ruled out today</h2>
            <span className="text-muted">{ruled_out.length}</span>
            <span aria-hidden="true" className="ml-auto text-sm text-accent group-open:hidden">
              Show
            </span>
            <span aria-hidden="true" className="ml-auto hidden text-sm text-accent group-open:inline">
              Hide
            </span>
          </summary>
          <p className="mt-1 mb-4 text-[0.9375rem] text-muted">
            These fit your profile, but a dealbreaker excluded them. “Couldn’t check” means the posting doesn’t say, and
            you asked us to be strict about that rule.
          </p>
          <RuledOutList items={ruled_out} />
        </details>
      )}
    </>
  );
}

function loadedText({ response, profile }: DailyMatches): string {
  if (!profile) return "No profile yet.";
  const n = response.results.length;
  const out = response.ruled_out.length;
  return `${n === 0 ? "No" : n} ${n === 1 ? "match" : "matches"} today${out ? `, ${out} ruled out` : ""}.`;
}

function NoProfile() {
  return (
    <EmptyState title="Tell us what you’re looking for">
      <p>
        Matches come from your skills, level, location and dealbreakers. It takes about two minutes, and it stays on
        this device.
      </p>
      <Link
        href="/onboarding"
        className="mt-5 inline-flex h-11 items-center rounded-md border border-accent bg-accent px-4 text-sm font-medium text-surface hover:bg-accent-hover"
      >
        Set up your profile
      </Link>
    </EmptyState>
  );
}

function EmptyState({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="border-y border-rule py-10">
      <h2 className="font-serif text-2xl font-medium">{title}</h2>
      <div className="mt-2 max-w-prose text-[0.9375rem] leading-relaxed text-muted">{children}</div>
    </section>
  );
}

function Loading() {
  return (
    <div>
      <p role="status" className="sr-only">
        Finding today’s matches…
      </p>
      <ol aria-hidden="true" className="border-b border-rule">
        {[0, 1, 2].map((i) => (
          <li key={i} className="grid gap-x-8 border-t border-rule py-8 sm:grid-cols-[2.5rem_1fr]">
            <div className="hidden h-7 w-5 rounded-sm bg-rule/60 motion-safe:animate-pulse sm:block" />
            <div className="space-y-3">
              <div className="h-4 w-48 rounded-sm bg-rule/60 motion-safe:animate-pulse" />
              <div className="h-7 w-3/4 rounded-sm bg-rule/70 motion-safe:animate-pulse" />
              <div className="h-4 w-2/3 rounded-sm bg-rule/50 motion-safe:animate-pulse" />
              <div className="grid gap-6 pt-3 md:grid-cols-2">
                <div className="h-20 rounded-sm bg-rule/40 motion-safe:animate-pulse" />
                <div className="h-20 rounded-sm bg-rule/40 motion-safe:animate-pulse" />
              </div>
            </div>
          </li>
        ))}
      </ol>
    </div>
  );
}

/** How long the rate-limit state waits before "Try again" is enabled. */
export const RATE_LIMIT_WAIT_S = 30;

/**
 * "Try again" disabled for `seconds`, counting down on the button. Screen readers hear it
 * twice, not every second: the wait when it starts (the body text says it) and "You can
 * try again now." when the button is enabled.
 */
function CountdownRetry({ seconds, onRetry }: { seconds: number; onRetry: () => void }) {
  const [left, setLeft] = useState(seconds);
  // Counted from the clock, not by ticks, so a throttled background tab stays right.
  useEffect(() => {
    const end = Date.now() + seconds * 1000;
    const timer = setInterval(() => {
      const remaining = Math.max(0, Math.ceil((end - Date.now()) / 1000));
      setLeft(remaining);
      if (remaining === 0) clearInterval(timer);
    }, 250);
    return () => clearInterval(timer);
  }, [seconds]);
  const waiting = left > 0;
  return (
    <>
      <Button onClick={onRetry} disabled={waiting} aria-describedby="retry-wait">
        Try again
        {waiting && (
          <span aria-hidden="true" className="tabular-nums">
            {` in ${left}s`}
          </span>
        )}
      </Button>
      <p id="retry-wait" className="sr-only" aria-live="polite">
        {waiting ? "" : "You can try again now."}
      </p>
    </>
  );
}

function ErrorState({ error, onRetry }: { error: ApiError; onRetry: () => void }) {
  let title = "Today’s matches didn’t load";
  let body = "Something went wrong on our side. Your profile and saved jobs are safe.";
  if (error.code === "network") {
    title = "Can’t reach JobMatch right now";
    body = "Check your connection. If it’s fine, our server may be restarting; try again in a minute.";
  } else if (error.status === 401) {
    title = "Your session has ended";
    body = "Sign in again to see today’s matches.";
  } else if (error.status === 429) {
    title = "Too many searches in a short time";
    body = `Wait ${RATE_LIMIT_WAIT_S} seconds, then try again.`;
  }
  return (
    <section role="alert" className="rounded-md border border-danger/40 bg-danger-bg px-5 py-6">
      <h2 className="font-serif text-2xl font-medium">{title}</h2>
      <p className="mt-2 max-w-prose text-[0.9375rem]">{body}</p>
      <div className="mt-5">
        {error.status === 401 ? (
          <Link
            href="/login"
            className="inline-flex h-11 items-center rounded-md border border-accent bg-accent px-4 text-sm font-medium text-surface hover:bg-accent-hover"
          >
            Sign in
          </Link>
        ) : error.status === 429 ? (
          <CountdownRetry seconds={RATE_LIMIT_WAIT_S} onRetry={onRetry} />
        ) : (
          <Button onClick={onRetry}>Try again</Button>
        )}
      </div>
    </section>
  );
}

function ScenarioNav({ current }: { current: Scenario }) {
  return (
    <nav aria-label="Review states (test data only)" className="mt-16 border-t border-dashed border-rule pt-4 text-sm">
      <p className="text-muted">Review states (test data only):</p>
      <ul className="mt-2 flex flex-wrap gap-x-4 gap-y-1">
        {SCENARIOS.map((s) => (
          <li key={s}>
            <Link
              href={s === "default" ? "/matches" : `/matches?state=${s}`}
              aria-current={s === current ? "page" : undefined}
              className={`inline-flex min-h-8 items-center underline-offset-4 ${s === current ? "font-medium text-ink underline decoration-accent" : "text-accent underline decoration-rule hover:decoration-accent"}`}
            >
              {s}
            </Link>
          </li>
        ))}
      </ul>
    </nav>
  );
}
