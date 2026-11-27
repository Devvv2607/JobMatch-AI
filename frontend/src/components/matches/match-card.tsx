"use client";

import { useId, useState } from "react";

import { CompanyMark } from "./company-mark";
import { FeedbackControls, REASON_LABELS } from "./feedback-controls";
import { useJobFeedback } from "@/lib/feedback";
import { experienceText, formatSalary, label, postedAge, preferenceText, sourceName } from "@/lib/format";
import type { ExplanationSentence, JobExtras, SearchResult } from "@/lib/types";

/** "Posted 14 months ago · reposted 3 times · seen at 2 sources": facts only, each when known. */
export function factsLine(postedAt: string | null, extras: JobExtras, now?: Date): string[] {
  const parts: string[] = [];
  const age = postedAge(postedAt, now);
  if (age) parts.push(age);
  if (extras.repost_count) parts.push(`reposted ${extras.repost_count} ${extras.repost_count === 1 ? "time" : "times"}`);
  if (extras.source_count && extras.source_count > 1) parts.push(`seen at ${extras.source_count} sources`);
  return parts;
}

function Marker({ kind }: { kind: "plus" | "gap" | "flag" }) {
  const glyph = kind === "plus" ? "+" : kind === "gap" ? "–" : "?";
  const tone = kind === "plus" ? "text-accent" : "text-muted";
  return (
    <span aria-hidden="true" className={`w-4 shrink-0 font-mono text-sm leading-6 ${tone}`}>
      {glyph}
    </span>
  );
}

function Item({ kind, children }: { kind: "plus" | "gap" | "flag"; children: React.ReactNode }) {
  return (
    <li className="flex gap-2 text-[0.9375rem] leading-6">
      <Marker kind={kind} />
      <span className="min-w-0">{children}</span>
    </li>
  );
}

function Skills({ skills }: { skills: string[] }) {
  return <span className="font-medium">{skills.join(", ")}</span>;
}

type Props = {
  result: SearchResult;
  extras?: JobExtras;
  sentence?: ExplanationSentence;
};

export function MatchCard({ result, extras = {}, sentence }: Props) {
  const { job, explanation, rank } = result;
  const feedback = useJobFeedback(job.id);
  const [expanded, setExpanded] = useState(false);
  const titleId = useId();
  const descriptionId = useId();
  const whyId = useId();
  const gapsId = useId();

  if (feedback.current?.action === "dismissed") {
    const reason = feedback.current.reason;
    return (
      <article aria-labelledby={titleId} className="border-t border-rule py-5">
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2 text-sm text-muted">
          <p id={titleId}>
            Hidden: <span className="text-ink">{job.title}</span> at {job.company}
            {reason ? ` — ${REASON_LABELS[reason].toLowerCase()}` : ""}
          </p>
          <button
            type="button"
            onClick={feedback.clear}
            className="h-11 text-accent underline decoration-rule underline-offset-4 hover:decoration-accent"
          >
            Undo<span className="sr-only">: show {job.title} again</span>
          </button>
        </div>
      </article>
    );
  }

  const { skills, experience, preferences, flags } = explanation;
  const exp = experienceText(experience);
  const prefsMet = preferences.filter((p) => p.match === true);
  const prefsGap = preferences.filter((p) => p.match !== true);
  const facts = factsLine(job.posted_at, extras);
  const snippet = extras.description_quality === "snippet";
  const description = extras.description?.trim();
  const long = !!description && !snippet && description.length > 420;

  const meta = [
    formatSalary(job.salary),
    label(job.remote_policy),
    label(job.employment_type),
    label(job.seniority),
  ];

  const hasGaps = skills.missing.length > 0 || (exp && !exp.good) || prefsGap.length > 0 || flags.length > 0;

  return (
    <article aria-labelledby={titleId} className="grid gap-x-8 border-t border-rule py-8 sm:grid-cols-[2.5rem_1fr]">
      <p aria-hidden="true" className="hidden font-serif text-3xl leading-none text-muted sm:block">
        {rank}
      </p>
      <div className="min-w-0">
        <div className="flex items-center gap-3 text-sm">
          <CompanyMark company={job.company} logoUrl={extras.logo_url} />
          <p className="min-w-0 truncate">
            <span className="font-medium">{job.company}</span>
            <span className="text-muted"> · {job.location}</span>
          </p>
        </div>

        <h3 id={titleId} className="mt-3 font-serif text-2xl leading-snug font-medium tracking-tight text-balance">
          <span className="sr-only">Match {rank}: </span>
          {job.title}
        </h3>

        <ul className="mt-2 flex flex-wrap gap-x-2 text-[0.9375rem]" aria-label="Key facts">
          {meta.map((part, i) => (
            <li key={part + i} className={i === 0 && job.salary.min == null && job.salary.max == null ? "text-muted" : ""}>
              {i > 0 && (
                <span aria-hidden="true" className="mr-2 text-rule">
                  /
                </span>
              )}
              {part}
            </li>
          ))}
        </ul>

        {facts.length > 0 && <p className="mt-1 text-sm text-muted">{facts.join(" · ")}</p>}

        {(extras.poster_type === "staffing_agency" || extras.eligibility_scope === "worldwide") && (
          <ul className="mt-3 flex flex-wrap gap-2 text-sm">
            {extras.poster_type === "staffing_agency" && (
              <li className="rounded-sm border border-rule px-2 py-0.5">Posted by a staffing agency</li>
            )}
            {extras.eligibility_scope === "worldwide" && (
              <li className="rounded-sm border border-rule px-2 py-0.5">Open to applicants worldwide</li>
            )}
          </ul>
        )}

        <div className="mt-6 grid gap-6 md:grid-cols-2 md:gap-10">
          <section aria-labelledby={`${whyId} ${titleId}`}>
            <h4 id={whyId} className="text-xs font-semibold tracking-[0.08em] text-muted uppercase">
              Why it matches
            </h4>
            <ul className="mt-2 space-y-1.5">
              {skills.matched.length > 0 && (
                <Item kind="plus">
                  {skills.matched.length === skills.matched.length + skills.missing.length
                    ? "All listed skills: "
                    : `${skills.matched.length} of ${skills.matched.length + skills.missing.length} listed skills: `}
                  <Skills skills={skills.matched} />
                </Item>
              )}
              {exp?.good && <Item kind="plus">{exp.text}</Item>}
              {prefsMet.map((p) => (
                <Item key={p.name} kind="plus">
                  {preferenceText(p)}
                </Item>
              ))}
            </ul>
            {sentence?.status === "ok" && sentence.sentence && (
              <p className="mt-3 border-l-2 border-accent-soft pl-3 font-serif text-[1.0625rem] leading-relaxed italic">
                {sentence.sentence}
              </p>
            )}
          </section>

          <section aria-labelledby={`${gapsId} ${titleId}`}>
            <h4 id={gapsId} className="text-xs font-semibold tracking-[0.08em] text-muted uppercase">
              Gaps
            </h4>
            {hasGaps ? (
              <ul className="mt-2 space-y-1.5">
                {skills.missing.length > 0 && (
                  <Item kind="gap">
                    Not on your profile: <Skills skills={skills.missing} />
                  </Item>
                )}
                {exp && !exp.good && <Item kind="gap">{exp.text}</Item>}
                {prefsGap.map((p) => (
                  <Item key={p.name} kind="gap">
                    {preferenceText(p)}
                  </Item>
                ))}
                {flags.map((f) => (
                  <Item key={f.kind} kind="flag">
                    {f.reason}: check before applying
                    <span className="block text-sm text-muted">Your dealbreaker: {f.rule}</span>
                  </Item>
                ))}
              </ul>
            ) : (
              <p className="mt-2 text-[0.9375rem] text-muted">None found in what the posting lists.</p>
            )}
          </section>
        </div>

        {description && (
          <div className="mt-6">
            {snippet && (
              <p className="mb-1 text-xs font-semibold tracking-[0.08em] text-muted uppercase">
                Short description from source
              </p>
            )}
            <p
              id={descriptionId}
              className={`text-[0.9375rem] leading-relaxed whitespace-pre-line text-ink/85 ${long && !expanded ? "line-clamp-4" : ""}`}
            >
              {description}
            </p>
            {snippet && (
              <p className="mt-1 text-sm text-muted">
                {sourceName(job.source)} shares only this excerpt. The full posting is on the source site.
              </p>
            )}
            {long && (
              <button
                type="button"
                aria-expanded={expanded}
                aria-controls={descriptionId}
                onClick={() => setExpanded((v) => !v)}
                className="mt-1 h-11 text-sm text-accent underline decoration-rule underline-offset-4 hover:decoration-accent"
              >
                {expanded ? "Show less" : "Show full description"}
              </button>
            )}
          </div>
        )}

        <FeedbackControls
          jobTitle={job.title}
          saved={feedback.current?.action === "saved"}
          onSave={feedback.save}
          onUnsave={feedback.clear}
          onDismiss={feedback.dismiss}
          sourceUrl={job.source_url}
          sourceName={sourceName(job.source)}
        />
      </div>
    </article>
  );
}
