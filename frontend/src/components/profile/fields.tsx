"use client";

import { useState } from "react";

import { CheckboxGroup, ChipInput, FieldError, Hint, Input, Select, Switch } from "@/components/form/controls";
import { country, label } from "@/lib/format";
import { INR_PER_USD, LAKH, type SalaryCurrency, usdHint } from "@/lib/fx";
import { COUNTRY_CODES, INDUSTRIES } from "@/lib/generated/taxonomy";
import {
  ALL_LEVELS,
  BACKERS,
  BACKER_LABELS,
  EMPLOYMENT_TYPES,
  LEVELS,
  LIMITS,
  RULE_KINDS,
  RULE_TITLES,
  STRICT_APPLIES,
  STRICT_TEXT,
  defaultSalaryCurrency,
  salaryAmount,
  salaryUsd,
  WORKPLACES,
  industryLabel,
  type Errors,
  type ProfileDraft,
  type RuleDrafts,
} from "@/lib/profile/model";
import { MAX_SKILL_LENGTH, canonicalSkill, collapse, suggestSkills } from "@/lib/skills";
import type { RuleKind } from "@/lib/types";

/** The id of the control a field's error belongs to (used to move focus to it). */
export const fieldId = (name: string) => `pf-${name}`;

export type FieldsProps = {
  draft: ProfileDraft;
  update: (change: (draft: ProfileDraft) => ProfileDraft) => void;
  errors: Errors;
};

// ---- Resume (a placeholder until 5c) ---------------------------------------------------

export const RESUME_MAX_BYTES = 5 * 1024 * 1024;
const RESUME_TYPES: Record<string, string> = {
  "application/pdf": "pdf",
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
};

export type ResumeFile = { name: string; size: number };

function megabytes(bytes: number): string {
  const mb = bytes / (1024 * 1024);
  return `${mb < 0.1 ? "under 0.1" : mb.toFixed(1)} MB`;
}

/** Checks a chosen file in the browser. Nothing is read or sent. */
export function checkResume(file: File): { ok: ResumeFile } | { error: string } {
  const extension = file.name.includes(".") ? file.name.split(".").pop()!.toLowerCase() : "";
  const typeOk = RESUME_TYPES[file.type] !== undefined || (file.type === "" && ["pdf", "docx"].includes(extension));
  if (!typeOk || !["pdf", "docx"].includes(extension)) {
    const what = extension ? `a .${extension} file` : "not a PDF or Word file";
    return { error: `That’s ${what}. Choose a PDF or a Word (.docx) file.` };
  }
  if (file.size === 0) return { error: "That file is empty. Choose another one." };
  if (file.size > RESUME_MAX_BYTES)
    return { error: `That file is ${megabytes(file.size)}. Choose one that’s 5 MB or smaller.` };
  return { ok: { name: file.name, size: file.size } };
}

export function ResumeField({ file, onChange }: { file: ResumeFile | null; onChange: (file: ResumeFile | null) => void }) {
  const [error, setError] = useState<string | null>(null);
  const id = fieldId("resume");
  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor={id} className="text-sm font-medium">
        Resume
      </label>
      <Hint id={`${id}-hint`}>PDF or Word (.docx), up to 5 MB. It stays on your device.</Hint>
      <input
        id={id}
        type="file"
        accept=".pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        aria-describedby={`${id}-hint${error ? ` ${id}-error` : ""}`}
        aria-invalid={error ? true : undefined}
        onChange={(event) => {
          const chosen = event.target.files?.[0];
          if (!chosen) return;
          const result = checkResume(chosen);
          if ("error" in result) {
            setError(result.error);
            onChange(null);
            event.target.value = "";
          } else {
            setError(null);
            onChange(result.ok);
          }
        }}
        className="mt-1 block w-full text-sm text-muted file:mr-4 file:h-11 file:cursor-pointer file:rounded-md file:border file:border-rule file:bg-surface file:px-4 file:text-sm file:font-medium file:text-ink hover:file:border-muted"
      />
      <FieldError id={`${id}-error`}>{error ?? undefined}</FieldError>
      {file && !error && (
        <p role="status" className="text-sm">
          {file.name} ({megabytes(file.size)}) looks fine. Nothing was uploaded.
        </p>
      )}
    </div>
  );
}

// ---- Skills ----------------------------------------------------------------------------

export function skillFromText(text: string): { value: string } | { error: string } {
  const value = canonicalSkill(text);
  if (!value) return { error: "Type a skill first." };
  if (value.length > MAX_SKILL_LENGTH) return { error: `Keep each skill under ${MAX_SKILL_LENGTH} characters.` };
  return { value };
}

export function SkillsFields({ draft, update, errors }: FieldsProps) {
  return (
    <ChipInput
      id={fieldId("skills")}
      label="Your skills"
      hint="Tools, languages and methods you’d be happy to be asked about. Press Enter or a comma after each."
      values={draft.skills}
      onChange={(skills) => update((d) => ({ ...d, skills }))}
      suggest={(q, chosen) => suggestSkills(q, chosen).map((s) => ({ value: s, label: s }))}
      fromText={skillFromText}
      error={errors.skills}
      max={LIMITS.skills}
      maxMessage={`You can add up to ${LIMITS.skills} skills.`}
      placeholder="Python, SQL, Airflow…"
      emptyText="No skills added yet."
    />
  );
}

// ---- Level and experience --------------------------------------------------------------

export function LevelFields({ draft, update, errors }: FieldsProps) {
  return (
    <div className="space-y-6">
      <CheckboxGroup
        id={fieldId("levels")}
        legend="Levels you’d take"
        hint="Pick more than one if you’re between levels."
        options={LEVELS}
        labelFor={label}
        values={draft.levels}
        onChange={(levels) => update((d) => ({ ...d, levels }))}
        error={errors.levels}
      />
      <Input
        id={fieldId("years")}
        label="Years of experience"
        hint="Paid work in your field, internships included. Leave it blank if you’re starting out."
        value={draft.years}
        onChange={(years) => update((d) => ({ ...d, years }))}
        inputMode="decimal"
        suffix="years"
        error={errors.years}
        className="max-w-56"
      />
      <Input
        id={fieldId("field")}
        label="Field"
        hint="What you do, in a few words, like “Data engineering”. We search with it."
        value={draft.field}
        onChange={(field) => update((d) => ({ ...d, field }))}
        error={errors.field}
        placeholder="Data engineering"
      />
    </div>
  );
}

// ---- Where and how ---------------------------------------------------------------------

const COUNTRY_OPTIONS = COUNTRY_CODES.map((code) => ({ value: code, label: country(code) })).sort((a, b) =>
  a.label.localeCompare(b.label),
);

function suggestCountries(query: string, chosen: string[]) {
  const q = collapse(query).toLowerCase();
  return COUNTRY_OPTIONS.filter(
    (o) => !chosen.includes(o.value) && (o.label.toLowerCase().startsWith(q) || o.value.toLowerCase() === q),
  ).slice(0, 8);
}

function countryFromText(text: string): { value: string } | { error: string } {
  const q = collapse(text).toLowerCase();
  const hit = COUNTRY_OPTIONS.find((o) => o.label.toLowerCase() === q || o.value.toLowerCase() === q);
  return hit ? { value: hit.value } : { error: `We don’t know “${collapse(text)}” as a country yet. Pick one from the list.` };
}

export function WhereFields({ draft, update, errors }: FieldsProps) {
  return (
    <div className="space-y-6">
      <ChipInput
        id={fieldId("countries")}
        label="Countries you’d work in"
        hint="Where you live, or would move to. Remote jobs open to these count too."
        values={draft.countries}
        onChange={(countries) => update((d) => ({ ...d, countries }))}
        suggest={suggestCountries}
        fromText={countryFromText}
        labelFor={country}
        error={errors.countries}
        max={LIMITS.countries}
        maxMessage={`You can pick up to ${LIMITS.countries} countries.`}
        placeholder="India"
        emptyText="No countries added yet."
      />
      <CheckboxGroup
        // Not "workplace": that id and error key belong to the workplace dealbreaker.
        id={fieldId("preferred_workplace")}
        legend="Ways of working you’d like"
        hint="A preference: it moves matching jobs up. To hide the others, use the workplace dealbreaker."
        options={WORKPLACES}
        labelFor={label}
        values={draft.workplace}
        onChange={(workplace) => update((d) => ({ ...d, workplace }))}
        error={errors.preferred_workplace}
      />
    </div>
  );
}

// ---- Dealbreakers ----------------------------------------------------------------------

const RULE_HELP: Record<RuleKind, string> = {
  work_eligibility: "Hide jobs that can’t be done from this country.",
  location: "Hide jobs that aren’t in one of these places.",
  workplace: "Hide jobs that aren’t one of these.",
  min_salary_usd: "Hide jobs that pay less, comparing the top of the posted range in US dollars a year.",
  seniority: "Hide jobs at other levels.",
  employment_type: "Hide other kinds of employment.",
  posted_within_days: "Hide postings older than this.",
  exclude_industries: "Hide jobs at companies in these industries.",
  exclude_companies: "Hide jobs at these companies.",
  startup_backed: "Show only companies backed by Y Combinator or a VC firm.",
  exclude_staffing_agencies: "Hide jobs posted by recruiters or staffing firms for a client.",
  exclude_freelance_gigs: "Hide per-task or per-hour gig work, such as AI training or rating.",
};

function placeFromText(text: string): { value: string } | { error: string } {
  const value = collapse(text);
  if (!value) return { error: "Type a place first." };
  if (value.length > LIMITS.placeLength) return { error: `Keep each place under ${LIMITS.placeLength} characters.` };
  return { value };
}

function companyFromText(text: string): { value: string } | { error: string } {
  const value = collapse(text);
  if (!value) return { error: "Type a company name first." };
  if (value.length > LIMITS.companyLength) return { error: `Keep each name under ${LIMITS.companyLength} characters.` };
  return { value };
}

/** What a rule starts with when it's turned on, taken from the answers so far. */
function seeded(kind: RuleKind, draft: ProfileDraft): Partial<RuleDrafts[RuleKind]> {
  const r = draft.rules;
  switch (kind) {
    case "work_eligibility":
      return r.work_eligibility.country ? {} : { country: draft.countries[0] ?? "" };
    case "workplace":
      return r.workplace.allowed.length ? {} : { allowed: [...draft.workplace] };
    case "seniority":
      return r.seniority.allowed.length ? {} : { allowed: [...draft.levels] };
    case "min_salary_usd":
      return r.min_salary_usd.amount.trim() ? {} : { currency: defaultSalaryCurrency(draft.countries) };
    default:
      return {};
  }
}

const CURRENCY_OPTIONS: { value: SalaryCurrency; label: string }[] = [
  { value: "INR", label: "₹ lakhs a year (LPA)" },
  { value: "USD", label: "US dollars a year" },
];

const RATE_DATE = new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short", year: "numeric" }).format(
  new Date(`${INR_PER_USD.asOf}T00:00:00Z`),
);

function SalaryValue({
  rule,
  onChange,
  error,
}: {
  rule: RuleDrafts["min_salary_usd"];
  onChange: (patch: Partial<RuleDrafts["min_salary_usd"]>) => void;
  error?: string;
}) {
  const id = fieldId("min_salary_usd");
  const usd = salaryUsd(rule);
  const inr = rule.currency === "INR";

  // Switching currency converts what was typed, so nothing has to be re-entered.
  function setCurrency(currency: SalaryCurrency) {
    if (currency === rule.currency) return;
    const amount = salaryAmount(rule);
    if (amount === null) return onChange({ currency });
    const converted =
      currency === "USD"
        ? String(usd)
        : String(Math.round(((amount * INR_PER_USD.rate) / LAKH) * 100) / 100);
    onChange({ currency, amount: converted });
  }

  return (
    <div className="flex flex-col gap-4 sm:flex-row sm:items-start">
      <div className="sm:w-60">
        <Select
          id={fieldId("min_salary_usd-currency")}
          label="Currency"
          value={rule.currency}
          onChange={(v) => setCurrency(v as SalaryCurrency)}
          options={CURRENCY_OPTIONS}
        />
      </div>
      <div className="flex min-w-0 flex-col gap-1.5">
        <Input
          id={id}
          label="At least"
          value={rule.amount}
          onChange={(amount) => onChange({ amount })}
          inputMode={inr ? "decimal" : "numeric"}
          placeholder={inr ? "8" : "30000"}
          suffix={inr ? "LPA" : "USD a year"}
          error={error}
          hint={inr ? `Converted at ₹${INR_PER_USD.rate} to the dollar (rate of ${RATE_DATE}).` : undefined}
          className="max-w-64"
        />
        {inr && (
          <p aria-live="polite" className="text-sm font-medium">
            {usd !== null && usd > 0 && !error ? usdHint(usd) : ""}
          </p>
        )}
      </div>
    </div>
  );
}

function RuleValue({ kind, draft, setRule, error }: RuleProps) {
  const id = fieldId(kind);
  const r = draft.rules;
  switch (kind) {
    case "work_eligibility":
      return (
        <Select
          id={id}
          label="Country"
          value={r.work_eligibility.country}
          onChange={(country) => setRule(kind, { country })}
          options={COUNTRY_OPTIONS}
          placeholder="Choose a country"
          error={error}
        />
      );
    case "location":
      return (
        <ChipInput
          id={id}
          label="Cities, states or countries"
          hint="As a posting would write them, like “Bengaluru” or “Karnataka”. A job in any of them is kept."
          values={r.location.places}
          onChange={(places) => setRule(kind, { places })}
          fromText={placeFromText}
          error={error}
          max={LIMITS.places}
          maxMessage={`You can add up to ${LIMITS.places} places.`}
          placeholder="Bengaluru"
          emptyText="No places added yet."
        />
      );
    case "exclude_staffing_agencies":
    case "exclude_freelance_gigs":
      return null;
    case "workplace":
      return (
        <CheckboxGroup
          id={id}
          legend="Keep jobs that are"
          options={WORKPLACES}
          labelFor={label}
          values={r.workplace.allowed}
          onChange={(allowed) => setRule(kind, { allowed })}
          error={error}
        />
      );
    case "min_salary_usd":
      return <SalaryValue rule={r.min_salary_usd} onChange={(patch) => setRule(kind, patch)} error={error} />;
    case "seniority":
      return (
        <CheckboxGroup
          id={id}
          legend="Keep jobs at these levels"
          options={ALL_LEVELS}
          labelFor={label}
          values={r.seniority.allowed}
          onChange={(allowed) => setRule(kind, { allowed })}
          error={error}
          columns
        />
      );
    case "employment_type":
      return (
        <CheckboxGroup
          id={id}
          legend="Keep jobs that are"
          options={EMPLOYMENT_TYPES}
          labelFor={label}
          values={r.employment_type.allowed}
          onChange={(allowed) => setRule(kind, { allowed })}
          error={error}
        />
      );
    case "posted_within_days":
      return (
        <Input
          id={id}
          label="Posted in the last"
          value={r.posted_within_days.days}
          onChange={(days) => setRule(kind, { days })}
          inputMode="numeric"
          suffix="days"
          error={error}
          className="max-w-56"
        />
      );
    case "exclude_industries":
      return (
        <CheckboxGroup
          id={id}
          legend="Avoid"
          options={INDUSTRIES}
          labelFor={industryLabel}
          values={r.exclude_industries.industries}
          onChange={(industries) => setRule(kind, { industries })}
          error={error}
          columns
        />
      );
    case "exclude_companies":
      return (
        <ChipInput
          id={id}
          label="Companies"
          values={r.exclude_companies.companies}
          onChange={(companies) => setRule(kind, { companies })}
          fromText={companyFromText}
          error={error}
          max={LIMITS.companies}
          maxMessage={`You can add up to ${LIMITS.companies} companies.`}
          emptyText="No companies added yet."
        />
      );
    case "startup_backed":
      return (
        <CheckboxGroup
          id={id}
          legend="Backed by"
          options={BACKERS}
          labelFor={(b) => BACKER_LABELS[b]}
          values={r.startup_backed.backers}
          onChange={(backers) => setRule(kind, { backers })}
          error={error}
        />
      );
  }
}

type RuleProps = {
  kind: RuleKind;
  draft: ProfileDraft;
  setRule: <K extends RuleKind>(kind: K, patch: Partial<RuleDrafts[K]>) => void;
  error?: string;
};

function RuleControl({ kind, draft, setRule, error }: RuleProps) {
  const rule = draft.rules[kind];
  return (
    <li className="border-t border-rule py-5">
      <div>
        <Switch
          id={fieldId(`${kind}-on`)}
          label={RULE_TITLES[kind]}
          description={RULE_HELP[kind]}
          checked={rule.on}
          onChange={(on) => setRule(kind, on ? { on, ...seeded(kind, draft) } : { on })}
        />
        {rule.on && (
          <div className="mt-4 space-y-4 sm:pl-[3.25rem]">
            <RuleValue kind={kind} draft={draft} setRule={setRule} error={error} />
            {STRICT_APPLIES.has(kind) && (
              <Switch
                id={fieldId(`${kind}-strict`)}
                size="sm"
                label="Strict"
                description={STRICT_TEXT[kind]}
                checked={rule.strict}
                onChange={(strict) => setRule(kind, { strict })}
              />
            )}
          </div>
        )}
      </div>
    </li>
  );
}

export function DealbreakerFields({ draft, update, errors }: FieldsProps) {
  const setRule = <K extends RuleKind>(kind: K, patch: Partial<RuleDrafts[K]>) =>
    update((d) => ({ ...d, rules: { ...d.rules, [kind]: { ...d.rules[kind], ...patch } } }));
  return (
    <div>
      <p className="max-w-prose text-[0.9375rem] leading-relaxed text-muted">
        A dealbreaker hides jobs that break it. When a posting doesn’t say, we keep the job and mark it “Couldn’t
        check”, unless you make the rule strict.
      </p>
      <ul className="mt-4 border-b border-rule">
        {RULE_KINDS.map((kind) => (
          <RuleControl key={kind} kind={kind} draft={draft} setRule={setRule} error={errors[kind]} />
        ))}
      </ul>
    </div>
  );
}
