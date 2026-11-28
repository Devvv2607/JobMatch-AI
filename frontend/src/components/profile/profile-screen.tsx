"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { Button } from "@/components/button";
import { ConfirmDialog, focusField } from "@/components/form/controls";
import { SiteHeader } from "@/components/site-header";
import { country, label } from "@/lib/format";
import { toUsdPerYear, usdHint } from "@/lib/fx";
import {
  BACKER_LABELS,
  RULE_TITLES,
  SECTION_FIELDS,
  draftFromStored,
  hasErrors,
  industryLabel,
  storedFromDraft,
  validateSection,
  type Errors,
  type ProfileDraft,
  type Section,
  type StoredProfile,
} from "@/lib/profile/model";
import { clearMyData, useStoredProfile, writeProfile } from "@/lib/profile/store";
import type { DealbreakerRule } from "@/lib/types";

import {
  DealbreakerFields,
  LevelFields,
  ResumeField,
  SkillsFields,
  WhereFields,
  fieldId,
  type FieldsProps,
  type ResumeFile,
} from "./fields";

const SECTIONS: { id: Section; title: string; Fields: (props: FieldsProps) => React.ReactNode }[] = [
  { id: "skills", title: "Skills", Fields: SkillsFields },
  { id: "level", title: "Level and experience", Fields: LevelFields },
  { id: "where", title: "Where and how you work", Fields: WhereFields },
  { id: "dealbreakers", title: "Dealbreakers", Fields: DealbreakerFields },
];

const SAVED_AT = new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "long", hour: "2-digit", minute: "2-digit" });

/** On the profile page only skills are asked for; the rest can stay empty, as in onboarding. */
const REQUIRED: Record<Section, boolean> = { skills: true, level: false, where: false, dealbreakers: false };

export function Profile() {
  const state = useStoredProfile();
  const [cleared, setCleared] = useState(false);
  const [confirmClear, setConfirmClear] = useState(false);
  const [clearFailed, setClearFailed] = useState(false);

  function onClear() {
    setConfirmClear(false);
    const ok = clearMyData();
    setClearFailed(!ok);
    setCleared(ok);
  }

  return (
    <div className="min-h-dvh">
      <SiteHeader current="profile" skipLabel="Skip to your profile" />
      <main id="main" className="mx-auto w-full max-w-3xl px-4 pt-10 pb-20 sm:px-6 sm:pt-14">
        <h1 className="font-serif text-4xl leading-tight font-medium tracking-tight sm:text-5xl">Your profile</h1>
        <p className="mt-3 max-w-prose text-muted">Your profile stays in this browser until accounts arrive.</p>

        <div className="mt-8">
          {state === null && (
            <p role="status" className="text-muted">
              Loading your profile…
            </p>
          )}
          {state?.status === "empty" && <EmptyProfile cleared={cleared} />}
          {state?.status === "error" && <UnreadableProfile reason={state.reason} />}
          {state?.status === "ready" && <ProfileSections stored={state.stored} />}
        </div>

        {state !== null && (
          <section aria-labelledby="your-data" className="mt-16 border-t border-rule pt-6">
            <h2 id="your-data" className="font-serif text-2xl font-medium">
              Your data
            </h2>
            <p className="mt-2 max-w-prose text-[0.9375rem] leading-relaxed text-muted">
              Your profile and the jobs you saved or hid are kept in this browser only. Clearing removes them from
              here; nothing is stored anywhere else.
            </p>
            {clearFailed && (
              <p role="alert" className="mt-3 text-sm text-danger">
                Your browser didn’t let us clear everything. Try again, or clear this site’s data in the browser
                settings.
              </p>
            )}
            <button
              type="button"
              onClick={() => setConfirmClear(true)}
              className="mt-4 inline-flex h-11 items-center rounded-md border border-danger/60 bg-surface px-4 text-sm font-medium text-danger hover:border-danger"
            >
              Clear my data
            </button>
          </section>
        )}

        {confirmClear && (
          <ConfirmDialog
            title="Clear your data?"
            confirmLabel="Clear my data"
            cancelLabel="Keep my data"
            tone="danger"
            onConfirm={onClear}
            onCancel={() => setConfirmClear(false)}
          >
            <p>This removes your profile and your saved and hidden jobs from this browser. It can’t be undone.</p>
          </ConfirmDialog>
        )}
      </main>
    </div>
  );
}

function EmptyProfile({ cleared }: { cleared: boolean }) {
  return (
    <section className="border-y border-rule py-10">
      {cleared && (
        <p role="status" className="mb-4 text-sm font-medium text-accent">
          Your data was cleared from this browser.
        </p>
      )}
      <h2 className="font-serif text-2xl font-medium">No profile yet</h2>
      <p className="mt-2 max-w-prose text-[0.9375rem] leading-relaxed text-muted">
        Add your skills, level and dealbreakers, and we’ll use them to pick today’s matches. It takes about two minutes.
      </p>
      <Link
        href="/onboarding"
        className="mt-5 inline-flex h-11 items-center rounded-md border border-accent bg-accent px-4 text-sm font-medium text-surface hover:bg-accent-hover"
      >
        Set up your profile
      </Link>
    </section>
  );
}

function UnreadableProfile({ reason }: { reason: "unreadable" | "damaged" }) {
  return (
    <section role="alert" className="rounded-md border border-danger/40 bg-danger-bg px-5 py-6">
      <h2 className="font-serif text-2xl font-medium">We couldn’t read your saved profile</h2>
      <p className="mt-2 max-w-prose text-[0.9375rem]">
        {reason === "unreadable"
          ? "Your browser is blocking storage for this site. Allow it, then reload this page."
          : "The copy in this browser is damaged. Set your profile up again, or clear your data below to start clean."}
      </p>
      {reason === "damaged" && (
        <Link
          href="/onboarding"
          className="mt-5 inline-flex h-11 items-center rounded-md border border-accent bg-accent px-4 text-sm font-medium text-surface hover:bg-accent-hover"
        >
          Set up your profile again
        </Link>
      )}
    </section>
  );
}

// ---- Sections --------------------------------------------------------------------------

function sectionSlice(section: Section, draft: ProfileDraft): unknown {
  switch (section) {
    case "skills":
      return draft.skills;
    case "level":
      return [draft.levels, draft.years, draft.field];
    case "where":
      return [draft.countries, draft.workplace];
    case "dealbreakers":
      return draft.rules;
  }
}

type Pending = { kind: "section"; section: Section } | { kind: "link"; href: string };

function ProfileSections({ stored }: { stored: StoredProfile }) {
  const router = useRouter();
  const [editing, setEditing] = useState<Section | null>(null);
  const [draft, setDraft] = useState<ProfileDraft>(() => draftFromStored(stored));
  const [errors, setErrors] = useState<Errors>({});
  const [saved, setSaved] = useState<Section | null>(null);
  const [saveFailed, setSaveFailed] = useState(false);
  const [pending, setPending] = useState<Pending | null>(null);
  const [resume, setResume] = useState<ResumeFile | null>(null);
  const focusAfter = useRef<string | null>(null);

  const baseline = draftFromStored(stored);
  const dirty =
    editing !== null && JSON.stringify(sectionSlice(editing, draft)) !== JSON.stringify(sectionSlice(editing, baseline));

  useEffect(() => {
    if (!focusAfter.current) return;
    focusField(focusAfter.current);
    focusAfter.current = null;
  });

  // Unsaved changes: warn on reload or closing the tab, and catch links on the page.
  useEffect(() => {
    if (!dirty) return;
    const onBeforeUnload = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };
    const onClick = (event: MouseEvent) => {
      if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey) return;
      const link = (event.target as Element | null)?.closest?.("a[href]");
      if (!link) return;
      const href = link.getAttribute("href")!;
      if (href.startsWith("#")) return;
      event.preventDefault();
      setPending({ kind: "link", href });
    };
    window.addEventListener("beforeunload", onBeforeUnload);
    document.addEventListener("click", onClick, true);
    return () => {
      window.removeEventListener("beforeunload", onBeforeUnload);
      document.removeEventListener("click", onClick, true);
    };
  }, [dirty]);

  function open(section: Section) {
    setDraft(draftFromStored(stored));
    setErrors({});
    setSaved(null);
    setSaveFailed(false);
    setEditing(section);
    focusAfter.current = fieldId(SECTION_FIELDS[section][0]!);
  }

  function requestEdit(section: Section) {
    if (dirty) setPending({ kind: "section", section });
    else open(section);
  }

  function close(section: Section) {
    setEditing(null);
    setErrors({});
    focusAfter.current = `edit-${section}`;
  }

  function update(change: (d: ProfileDraft) => ProfileDraft) {
    const next = change(draft);
    setDraft(next);
    if (editing && hasErrors(errors)) {
      const now = validateSection(editing, next, REQUIRED[editing]);
      setErrors(Object.fromEntries(Object.keys(errors).flatMap((k) => (now[k] ? [[k, now[k]]] : []))) as Errors);
    }
  }

  function save(event: React.FormEvent, section: Section) {
    event.preventDefault();
    const problems = validateSection(section, draft, REQUIRED[section]);
    const first = SECTION_FIELDS[section].find((name) => problems[name]);
    if (first) {
      setErrors(problems);
      focusField(fieldId(first));
      return;
    }
    // Only this section changes; the rest stays as stored.
    const merged: ProfileDraft = { ...baseline };
    if (section === "skills") merged.skills = draft.skills;
    if (section === "level") Object.assign(merged, { levels: draft.levels, years: draft.years, field: draft.field });
    if (section === "where") Object.assign(merged, { countries: draft.countries, workplace: draft.workplace });
    if (section === "dealbreakers") merged.rules = draft.rules;
    if (!writeProfile(storedFromDraft(merged))) {
      setSaveFailed(true);
      return;
    }
    setSaved(section);
    close(section);
  }

  function discardAndContinue() {
    const next = pending;
    setPending(null);
    if (editing) close(editing);
    if (next?.kind === "section") open(next.section);
    if (next?.kind === "link") router.push(next.href);
  }

  const editingTitle = SECTIONS.find((s) => s.id === editing)?.title.toLowerCase();

  return (
    <div>
      <p className="text-sm text-muted">Last saved {SAVED_AT.format(new Date(stored.updated_at))}</p>

      <section aria-labelledby="resume-heading" className="mt-8 border-t border-rule py-8">
        <h2 id="resume-heading" className="font-serif text-2xl font-medium">
          Resume
        </h2>
        <p className="mt-1 mb-4 text-[0.9375rem] text-muted">
          Resume parsing is coming soon. For now, add your basics in the sections below.
        </p>
        <ResumeField file={resume} onChange={setResume} />
      </section>

      {SECTIONS.map(({ id, title, Fields }) => {
        const headingId = `${id}-heading`;
        const isEditing = editing === id;
        return (
          <section key={id} aria-labelledby={headingId} className="border-t border-rule py-8">
            <div className="flex items-baseline justify-between gap-4">
              <h2 id={headingId} className="font-serif text-2xl font-medium">
                {title}
              </h2>
              {!isEditing && (
                <button
                  id={`edit-${id}`}
                  type="button"
                  onClick={() => requestEdit(id)}
                  className="inline-flex h-11 items-center text-sm text-accent underline decoration-rule underline-offset-4 hover:decoration-accent"
                >
                  Edit <span className="sr-only">{title.toLowerCase()}</span>
                </button>
              )}
            </div>
            {saved === id && !isEditing && (
              <p role="status" className="mt-1 text-sm font-medium text-accent">
                Saved.
              </p>
            )}

            {isEditing ? (
              <form noValidate onSubmit={(e) => save(e, id)} aria-label={`Edit ${title.toLowerCase()}`} className="mt-4">
                <Fields draft={draft} update={update} errors={errors} />
                {saveFailed && (
                  <p role="alert" className="mt-4 text-sm text-danger">
                    Your browser didn’t let us save. It may be in private mode or out of space. Your changes are still
                    here.
                  </p>
                )}
                <div className="mt-6 flex flex-col-reverse gap-3 sm:flex-row">
                  <Button type="submit">Save</Button>
                  <Button type="button" variant="quiet" onClick={() => close(id)}>
                    Cancel
                  </Button>
                </div>
              </form>
            ) : (
              <Summary section={id} stored={stored} />
            )}
          </section>
        );
      })}

      {pending && (
        <ConfirmDialog
          title="Discard your changes?"
          confirmLabel="Discard changes"
          cancelLabel="Keep editing"
          onConfirm={discardAndContinue}
          onCancel={() => setPending(null)}
        >
          <p>You changed your {editingTitle} but haven’t saved.</p>
        </ConfirmDialog>
      )}
    </div>
  );
}

// ---- Read-only summaries ---------------------------------------------------------------

function Nothing({ children }: { children: string }) {
  return <span className="text-muted">{children}</span>;
}

function Facts({ rows }: { rows: [string, React.ReactNode][] }) {
  return (
    <dl className="mt-4 grid grid-cols-1 gap-x-8 gap-y-1 text-[0.9375rem] sm:grid-cols-[12rem_1fr] sm:gap-y-3">
      {rows.map(([term, value]) => (
        <div key={term} className="contents">
          <dt className="text-muted">{term}</dt>
          <dd className="mb-3 sm:mb-0">{value}</dd>
        </div>
      ))}
    </dl>
  );
}

const list = (values: string[]) => values.join(", ");

export function ruleSummary(rule: DealbreakerRule, stored?: StoredProfile): string {
  switch (rule.kind) {
    case "work_eligibility":
      return country(rule.country);
    case "location":
      return list(rule.places);
    case "exclude_staffing_agencies":
    case "exclude_freelance_gigs":
      return "On";
    case "workplace":
      return list(rule.allowed.map(label));
    case "min_salary_usd": {
      const typed = stored?.min_salary_input;
      if (typed?.currency === "INR" && toUsdPerYear(typed.amount, "INR") === rule.amount)
        return `At least ₹${typed.amount} LPA (${usdHint(rule.amount)})`;
      return `At least $${rule.amount.toLocaleString("en-US")} a year`;
    }
    case "seniority":
      return list(rule.allowed.map(label));
    case "employment_type":
      return list(rule.allowed.map(label));
    case "posted_within_days":
      return `Posted in the last ${rule.days} days`;
    case "exclude_industries":
      return list(rule.industries.map(industryLabel));
    case "exclude_companies":
      return list(rule.companies);
    case "startup_backed":
      return list(rule.backers.map((b) => BACKER_LABELS[b]));
  }
}

function Summary({ section, stored }: { section: Section; stored: StoredProfile }) {
  const { profile, rules, query } = stored;
  const prefs = profile.preferences ?? {};
  switch (section) {
    case "skills":
      return profile.skills?.length ? (
        <ul aria-label="Your skills" className="mt-4 flex flex-wrap gap-2">
          {profile.skills.map((s) => (
            <li key={s} className="rounded-sm border border-rule bg-surface px-2.5 py-1 text-[0.9375rem]">
              {s}
            </li>
          ))}
        </ul>
      ) : (
        <p className="mt-4 text-[0.9375rem] text-muted">No skills yet. Add a few so we can find matches.</p>
      );
    case "level":
      return (
        <Facts
          rows={[
            ["Levels you’d take", prefs.seniority?.length ? list(prefs.seniority.map(label)) : <Nothing>Not set</Nothing>],
            [
              "Experience",
              profile.years_experience == null ? (
                <Nothing>Not set</Nothing>
              ) : (
                `${profile.years_experience} ${profile.years_experience === 1 ? "year" : "years"}`
              ),
            ],
            ["Field", query ?? <Nothing>Not set</Nothing>],
          ]}
        />
      );
    case "where":
      return (
        <Facts
          rows={[
            ["Countries", prefs.countries?.length ? list(prefs.countries.map(country)) : <Nothing>Not set</Nothing>],
            ["Ways of working", prefs.workplace?.length ? list(prefs.workplace.map(label)) : <Nothing>Not set</Nothing>],
          ]}
        />
      );
    case "dealbreakers":
      return rules.length ? (
        <Facts
          rows={rules.map((rule) => [
            RULE_TITLES[rule.kind],
            <>
              {ruleSummary(rule, stored)}
              {rule.strict && <span className="ml-2 rounded-sm border border-rule px-1.5 py-0.5 text-xs">Strict</span>}
            </>,
          ])}
        />
      ) : (
        <p className="mt-4 text-[0.9375rem] text-muted">None set. Every job that fits your skills can show up.</p>
      );
  }
}
