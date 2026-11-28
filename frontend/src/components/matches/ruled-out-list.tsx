import { breachText, postedAge, sourceName } from "@/lib/format";
import type { RuledOut } from "@/lib/types";

/** Postings that matched the profile but a dealbreaker excluded, each with the rule. */
export function RuledOutList({ items }: { items: RuledOut[] }) {
  return (
    <ul className="divide-y divide-rule border-y border-rule">
      {items.map(({ job, rules }) => {
        // A stale posting's age comes from the API's note, as on the card.
        const age =
          job.stale_posting && job.age_note
            ? `Posted ${job.age_note.replace(/^posted /, "")}`
            : postedAge(job.posted_at);
        return (
          <li key={job.id} className="py-4">
            <div className="flex flex-col gap-x-6 gap-y-1 sm:flex-row sm:items-baseline sm:justify-between">
              <p className="min-w-0">
                <span className="font-medium">{job.title}</span>
                <span className="text-muted">
                  {" "}
                  · {job.company} · {job.location}
                </span>
              </p>
              <a
                href={job.source_url}
                target="_blank"
                rel="noopener noreferrer"
                className="shrink-0 text-sm text-accent underline decoration-rule underline-offset-4 hover:decoration-accent"
              >
                View on {sourceName(job.source)}
                <span className="sr-only">: {job.title} (opens in a new tab)</span>
              </a>
            </div>
            {age && <p className="text-sm text-muted">{age}</p>}
            <ul className="mt-2 space-y-1" aria-label="Why it was ruled out">
              {rules.map((breach) => {
                const { lead, detail } = breachText(breach);
                return (
                  <li key={breach.kind} className="flex gap-2 text-[0.9375rem] leading-6">
                    <span
                      aria-hidden="true"
                      className={`w-4 shrink-0 font-mono text-sm ${breach.outcome === "violates" ? "text-ink" : "text-muted"}`}
                    >
                      {breach.outcome === "violates" ? "×" : "?"}
                    </span>
                    <span>
                      {lead}
                      {detail && <span className="text-muted">: {detail.charAt(0).toLowerCase() + detail.slice(1)}</span>}
                    </span>
                  </li>
                );
              })}
            </ul>
          </li>
        );
      })}
    </ul>
  );
}
