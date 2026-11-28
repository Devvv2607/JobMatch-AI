"use client";

import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { Button } from "@/components/button";
import { focusField } from "@/components/form/controls";
import {
  DealbreakerFields,
  LevelFields,
  ResumeField,
  SkillsFields,
  WhereFields,
  fieldId,
  type ResumeFile,
} from "@/components/profile/fields";
import { SiteHeader } from "@/components/site-header";
import {
  SECTION_FIELDS,
  draftFromStored,
  hasErrors,
  storedFromDraft,
  validateSection,
  type Errors,
  type ProfileDraft,
  type Section,
} from "@/lib/profile/model";
import { useStoredProfile, writeProfile, type ProfileState } from "@/lib/profile/store";

type Step = { title: string; intro: string; sections: Section[] };

export const STEPS: Step[] = [
  { title: "Start with your resume", intro: "Resume parsing is coming soon. For now, add your basics in the next steps.", sections: [] },
  { title: "Your skills", intro: "We match these against the skills each posting asks for.", sections: ["skills"] },
  {
    title: "Level and experience",
    intro: "This helps us tell a stretch from a step down.",
    sections: ["level"],
  },
  {
    title: "Where and how you work",
    intro: "Where you can work, how you like to work, and what rules a job out.",
    sections: ["where", "dealbreakers"],
  },
];

function stepErrors(step: number, draft: ProfileDraft, required: boolean): Errors {
  return Object.assign({}, ...STEPS[step]!.sections.map((s) => validateSection(s, draft, required))) as Errors;
}

function firstError(errors: Errors): string | undefined {
  const order = Object.values(SECTION_FIELDS).flat();
  return order.find((name) => errors[name]);
}

/** Reads this browser's profile first, so a returning user starts from what they saved. */
export function Onboarding() {
  const state = useStoredProfile();
  if (state === null) {
    return (
      <main className="flex min-h-dvh items-center justify-center px-4" aria-busy="true">
        <p role="status" className="text-muted">
          Loading…
        </p>
      </main>
    );
  }
  return <OnboardingFlow state={state} />;
}

export function OnboardingFlow({ state }: { state: ProfileState }) {
  const router = useRouter();
  const [step, setStep] = useState(0);
  const [draft, setDraft] = useState<ProfileDraft>(() =>
    draftFromStored(state.status === "ready" ? state.stored : null),
  );
  const [resume, setResume] = useState<ResumeFile | null>(null);
  const [errors, setErrors] = useState<Errors>({});
  const [notice, setNotice] = useState<string | null>(null);
  const [saveFailed, setSaveFailed] = useState(false);
  const headingRef = useRef<HTMLHeadingElement>(null);
  const moved = useRef(false);
  const pendingFocus = useRef<string | null>(null);

  // Each step change moves focus to the step's heading (or to the field that needs fixing).
  useEffect(() => {
    if (!moved.current) return;
    if (pendingFocus.current) {
      focusField(fieldId(pendingFocus.current));
      pendingFocus.current = null;
    } else {
      headingRef.current?.focus();
    }
  }, [step]);

  const last = step === STEPS.length - 1;
  const current = STEPS[step]!;

  function update(change: (d: ProfileDraft) => ProfileDraft) {
    const next = change(draft);
    setDraft(next);
    // Clear a message as soon as its field is fixed; don't add new ones while typing.
    if (hasErrors(errors)) {
      const now = stepErrors(step, next, true);
      setErrors(Object.fromEntries(Object.keys(errors).flatMap((k) => (now[k] ? [[k, now[k]]] : []))) as Errors);
    }
  }

  function go(to: number) {
    moved.current = true;
    setErrors({});
    setNotice(null);
    setStep(to);
  }

  function finish() {
    // Skipped steps aren't asked for anything, but what was typed in them must still be valid.
    for (let i = 0; i < STEPS.length; i++) {
      const problems = stepErrors(i, draft, false);
      const name = firstError(problems);
      if (name) {
        moved.current = true;
        setErrors(problems);
        setNotice("One answer needs fixing before we can save your profile.");
        if (i === step) focusField(fieldId(name));
        else {
          pendingFocus.current = name;
          setStep(i);
        }
        return;
      }
    }
    if (!writeProfile(storedFromDraft(draft))) {
      setSaveFailed(true);
      return;
    }
    router.push("/matches");
  }

  function next(event: React.FormEvent) {
    event.preventDefault();
    const problems = stepErrors(step, draft, true);
    const name = firstError(problems);
    if (name) {
      setErrors(problems);
      focusField(fieldId(name));
      return;
    }
    if (last) finish();
    else go(step + 1);
  }

  function skip() {
    if (last) finish();
    else go(step + 1);
  }

  return (
    <div className="min-h-dvh">
      <SiteHeader skipLabel="Skip to the form" nav={false} />
      <main id="main" className="mx-auto w-full max-w-2xl px-4 pt-10 pb-20 sm:px-6 sm:pt-14">
        <p className="text-sm text-muted">Set up your profile</p>
        <nav aria-label="Progress" className="mt-3">
          <p className="text-sm font-medium">
            Step {step + 1} of {STEPS.length}
          </p>
          <ol className="mt-2 grid grid-cols-4 gap-1.5" aria-label="Steps">
            {STEPS.map((s, i) => (
              <li key={s.title} aria-current={i === step ? "step" : undefined}>
                <span aria-hidden="true" className={`block h-1 rounded-full ${i <= step ? "bg-accent" : "bg-rule"}`} />
                <span className="sr-only">
                  {s.title}
                  {i < step ? " (done)" : ""}
                </span>
              </li>
            ))}
          </ol>
        </nav>

        <h1
          ref={headingRef}
          tabIndex={-1}
          className="mt-8 font-serif text-4xl leading-tight font-medium tracking-tight outline-none sm:text-5xl"
        >
          {current.title}
        </h1>
        <p className="mt-3 max-w-prose text-muted">{current.intro}</p>
        {state.status === "error" && step === 0 && (
          <p className="mt-4 rounded-md border border-rule bg-surface px-4 py-3 text-sm">
            We couldn’t read the profile saved in this browser, so this starts fresh.
          </p>
        )}

        {notice && (
          <p role="alert" className="mt-6 rounded-md border border-danger/40 bg-danger-bg px-4 py-3 text-sm">
            {notice}
          </p>
        )}
        {saveFailed && (
          <div role="alert" className="mt-6 rounded-md border border-danger/40 bg-danger-bg px-4 py-3 text-sm">
            <p className="font-medium">Your browser didn’t let us save your profile.</p>
            <p className="mt-1">
              It may be in private mode or out of space. Your answers are still here; try again, or allow this site to
              store data.
            </p>
          </div>
        )}

        <form noValidate onSubmit={next} className="mt-8">
          {step === 0 && <ResumeField file={resume} onChange={setResume} />}
          {step === 1 && <SkillsFields draft={draft} update={update} errors={errors} />}
          {step === 2 && <LevelFields draft={draft} update={update} errors={errors} />}
          {step === 3 && (
            <div className="space-y-10">
              <WhereFields draft={draft} update={update} errors={errors} />
              <section aria-labelledby="dealbreakers-heading">
                <h2 id="dealbreakers-heading" className="font-serif text-2xl font-medium">
                  Dealbreakers
                </h2>
                <div className="mt-2">
                  <DealbreakerFields draft={draft} update={update} errors={errors} />
                </div>
              </section>
            </div>
          )}

          <div className="mt-10 flex flex-col-reverse gap-3 border-t border-rule pt-6 sm:flex-row sm:items-center">
            {step > 0 && (
              <Button type="button" variant="quiet" onClick={() => go(step - 1)}>
                Back
              </Button>
            )}
            <button
              type="button"
              onClick={skip}
              className="inline-flex h-11 items-center justify-center px-2 text-sm text-accent underline decoration-rule underline-offset-4 hover:decoration-accent sm:ml-auto"
            >
              {last ? "Skip and finish" : "Skip this step"}
            </button>
            <Button type="submit">{last ? "Finish" : "Next"}</Button>
          </div>
        </form>
      </main>
    </div>
  );
}
