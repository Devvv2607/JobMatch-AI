"use client";

import { useEffect, useId, useRef, useState } from "react";

/* Shared form pieces for onboarding and the profile page. They use only the design
 * tokens in globals.css, so a design change lands on every screen at once. */

export const INPUT =
  "h-11 w-full rounded-md border bg-surface px-3 text-base outline-none transition-colors placeholder:text-muted focus-visible:border-accent focus-visible:outline-1";

export function inputBorder(error?: string) {
  return error ? "border-danger" : "border-rule hover:border-muted";
}

export function Hint({ id, children }: { id: string; children: React.ReactNode }) {
  return (
    <p id={id} className="text-sm text-muted">
      {children}
    </p>
  );
}

export function FieldError({ id, children }: { id: string; children?: string }) {
  if (!children) return null;
  return (
    <p id={id} className="text-sm text-danger">
      {children}
    </p>
  );
}

function describedBy(...ids: unknown[]) {
  return ids.filter(Boolean).join(" ") || undefined;
}

// ---- Text input ----------------------------------------------------------------------

type InputProps = {
  id: string;
  label: string;
  value: string;
  onChange: (value: string) => void;
  hint?: React.ReactNode;
  error?: string;
  inputMode?: "text" | "decimal" | "numeric";
  placeholder?: string;
  autoComplete?: string;
  suffix?: string;
  /** A line under the field (e.g. a conversion), read as part of its description. */
  note?: React.ReactNode;
  className?: string;
};

export function Input({ id, label, value, onChange, hint, error, suffix, note, className = "", ...rest }: InputProps) {
  const hintId = `${id}-hint`;
  const errorId = `${id}-error`;
  const noteId = `${id}-note`;
  return (
    <div className={`flex flex-col gap-1.5 ${className}`}>
      <label htmlFor={id} className="text-sm font-medium">
        {label}
      </label>
      {hint && <Hint id={hintId}>{hint}</Hint>}
      <div className="flex items-center gap-2">
        <input
          id={id}
          type="text"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          aria-invalid={error ? true : undefined}
          aria-describedby={describedBy(hint && hintId, error && errorId, note && noteId)}
          className={`${INPUT} ${inputBorder(error)}`}
          {...rest}
        />
        {suffix && <span className="shrink-0 text-sm text-muted">{suffix}</span>}
      </div>
      <FieldError id={errorId}>{error}</FieldError>
      {note && (
        <p id={noteId} className="text-sm text-muted">
          {note}
        </p>
      )}
    </div>
  );
}

// ---- Select --------------------------------------------------------------------------

type SelectProps = {
  id: string;
  label: string;
  value: string;
  onChange: (value: string) => void;
  options: { value: string; label: string }[];
  /** A first, empty choice; omit when a value is always chosen. */
  placeholder?: string;
  hint?: React.ReactNode;
  error?: string;
};

export function Select({ id, label, value, onChange, options, placeholder, hint, error }: SelectProps) {
  const hintId = `${id}-hint`;
  const errorId = `${id}-error`;
  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor={id} className="text-sm font-medium">
        {label}
      </label>
      {hint && <Hint id={hintId}>{hint}</Hint>}
      <select
        id={id}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        aria-invalid={error ? true : undefined}
        aria-describedby={describedBy(hint && hintId, error && errorId)}
        className={`${INPUT} ${inputBorder(error)} appearance-auto`}
      >
        {placeholder !== undefined && <option value="">{placeholder}</option>}
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
      <FieldError id={errorId}>{error}</FieldError>
    </div>
  );
}

// ---- Checkbox group ------------------------------------------------------------------

type CheckboxGroupProps<T extends string> = {
  id: string;
  legend: string;
  options: readonly T[];
  labelFor: (value: T) => string;
  values: readonly T[];
  onChange: (values: T[]) => void;
  hint?: React.ReactNode;
  error?: string;
  legendClassName?: string;
  columns?: boolean;
};

export function CheckboxGroup<T extends string>({
  id,
  legend,
  options,
  labelFor,
  values,
  onChange,
  hint,
  error,
  legendClassName = "text-sm font-medium",
  columns = false,
}: CheckboxGroupProps<T>) {
  const hintId = `${id}-hint`;
  const errorId = `${id}-error`;
  const toggle = (value: T, checked: boolean) =>
    onChange(checked ? [...values, value] : values.filter((v) => v !== value));
  return (
    <fieldset
      id={id}
      aria-describedby={describedBy(hint && hintId, error && errorId)}
      aria-invalid={error ? true : undefined}
      className="min-w-0"
    >
      <legend className={legendClassName}>{legend}</legend>
      {hint && (
        <div className="mt-1">
          <Hint id={hintId}>{hint}</Hint>
        </div>
      )}
      <ul className={`mt-2 ${columns ? "grid grid-cols-1 gap-x-6 sm:grid-cols-2" : "flex flex-wrap gap-x-6"}`}>
        {options.map((option) => (
          <li key={option}>
            <label className="flex min-h-11 cursor-pointer items-center gap-2.5 text-[0.9375rem]">
              <input
                type="checkbox"
                checked={values.includes(option)}
                onChange={(e) => toggle(option, e.target.checked)}
                className="size-4 shrink-0 accent-accent"
              />
              {labelFor(option)}
            </label>
          </li>
        ))}
      </ul>
      <FieldError id={errorId}>{error}</FieldError>
    </fieldset>
  );
}

// ---- Switch --------------------------------------------------------------------------

type SwitchProps = {
  id: string;
  label: React.ReactNode;
  checked: boolean;
  onChange: (checked: boolean) => void;
  description?: React.ReactNode;
  size?: "md" | "sm";
};

export function Switch({ id, label, checked, onChange, description, size = "md" }: SwitchProps) {
  const labelId = `${id}-label`;
  const descriptionId = `${id}-description`;
  return (
    <div className="flex items-start gap-3">
      <button
        id={id}
        type="button"
        role="switch"
        aria-checked={checked}
        aria-labelledby={labelId}
        aria-describedby={description ? descriptionId : undefined}
        onClick={() => onChange(!checked)}
        className="group -my-1.5 inline-flex h-11 shrink-0 items-center"
      >
        <span
          aria-hidden="true"
          className={`relative inline-flex h-6 w-10 items-center rounded-full border transition-colors ${
            checked ? "border-accent bg-accent" : "border-muted bg-surface"
          }`}
        >
          <span
            className={`absolute left-0.5 size-4.5 rounded-full motion-safe:transition-transform ${
              checked ? "translate-x-4 bg-surface" : "translate-x-0 bg-muted"
            }`}
          />
        </span>
      </button>
      <div className="min-w-0 pt-0.5">
        <span id={labelId} className={size === "md" ? "text-[0.9375rem] font-medium" : "text-sm font-medium"}>
          {label}
        </span>
        {description && (
          <p id={descriptionId} className="text-sm text-muted">
            {description}
          </p>
        )}
      </div>
    </div>
  );
}

// ---- Chips with autocomplete ---------------------------------------------------------

export type Suggestion = { value: string; label: string };

type ChipInputProps = {
  id: string;
  label: string;
  values: string[];
  onChange: (values: string[]) => void;
  /** What to suggest for the typed text; return [] for none. */
  suggest?: (query: string, chosen: string[]) => Suggestion[];
  /** The value to add for typed text, or an error message. Omit to accept only suggestions. */
  fromText?: (text: string) => { value: string } | { error: string };
  labelFor?: (value: string) => string;
  hint?: React.ReactNode;
  error?: string;
  max: number;
  maxMessage: string;
  placeholder?: string;
  /** Spoken and shown when nothing has been added yet. */
  emptyText: string;
};

export function ChipInput({
  id,
  label,
  values,
  onChange,
  suggest,
  fromText,
  labelFor = (v) => v,
  hint,
  error,
  max,
  maxMessage,
  placeholder,
  emptyText,
}: ChipInputProps) {
  const [text, setText] = useState("");
  const [active, setActive] = useState(-1);
  const [open, setOpen] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [announcement, setAnnouncement] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);
  const listId = `${id}-options`;
  const hintId = `${id}-hint`;
  const errorId = `${id}-error`;
  const shownError = problem ?? error;

  const options = suggest && text.trim() ? suggest(text, values) : [];
  const expanded = open && options.length > 0;

  function add(candidates: string[]) {
    let next = [...values];
    const added: string[] = [];
    for (const raw of candidates) {
      if (!raw.trim()) continue;
      let value: string;
      const exact = options.find((o) => o.label.toLowerCase() === raw.trim().toLowerCase());
      if (exact) value = exact.value;
      else if (fromText) {
        const result = fromText(raw);
        if ("error" in result) {
          setProblem(result.error);
          return;
        }
        value = result.value;
      } else {
        setProblem(`Pick “${raw.trim()}” from the list, or check the spelling.`);
        return;
      }
      if (next.some((v) => v.toLowerCase() === value.toLowerCase())) {
        setProblem(`${labelFor(value)} is already on your list.`);
        return;
      }
      if (next.length >= max) {
        setProblem(maxMessage);
        return;
      }
      next = [...next, value];
      added.push(labelFor(value));
    }
    if (added.length === 0) return;
    onChange(next);
    setText("");
    setActive(-1);
    setOpen(false);
    setProblem(null);
    setAnnouncement(`Added ${added.join(", ")}.`);
  }

  function remove(value: string) {
    onChange(values.filter((v) => v !== value));
    setProblem(null);
    setAnnouncement(`Removed ${labelFor(value)}.`);
    inputRef.current?.focus();
  }

  function onKeyDown(event: React.KeyboardEvent<HTMLInputElement>) {
    if (event.key === "ArrowDown" && options.length > 0) {
      event.preventDefault();
      setOpen(true);
      setActive((i) => (i + 1) % options.length);
    } else if (event.key === "ArrowUp" && options.length > 0) {
      event.preventDefault();
      setOpen(true);
      setActive((i) => (i <= 0 ? options.length - 1 : i - 1));
    } else if (event.key === "Enter") {
      if (!text.trim()) return;
      event.preventDefault();
      if (expanded && active >= 0) add([options[active]!.label]);
      else add(fromText ? text.split(",") : [text]);
    } else if (event.key === "," && fromText) {
      event.preventDefault();
      add([text]);
    } else if (event.key === "Escape" && expanded) {
      event.preventDefault();
      setOpen(false);
      setActive(-1);
    }
  }

  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor={id} className="text-sm font-medium">
        {label}
      </label>
      {hint && <Hint id={hintId}>{hint}</Hint>}

      <ul aria-label={label} className="flex flex-wrap gap-2 py-1">
        {values.length === 0 ? (
          <li className="text-sm text-muted">{emptyText}</li>
        ) : (
          values.map((value) => (
            <li
              key={value}
              className="inline-flex items-center rounded-sm border border-rule bg-surface pl-2.5 text-[0.9375rem]"
            >
              {labelFor(value)}
              <button
                type="button"
                onClick={() => remove(value)}
                aria-label={`Remove ${labelFor(value)}`}
                className="ml-1 inline-flex size-9 items-center justify-center rounded-sm text-muted hover:text-ink"
              >
                <span aria-hidden="true">×</span>
              </button>
            </li>
          ))
        )}
      </ul>

      <div className="relative">
        <input
          ref={inputRef}
          id={id}
          type="text"
          role="combobox"
          aria-autocomplete="list"
          aria-expanded={expanded}
          aria-controls={listId}
          aria-activedescendant={expanded && active >= 0 ? `${listId}-${active}` : undefined}
          aria-invalid={shownError ? true : undefined}
          aria-describedby={describedBy(hint && hintId, shownError && errorId)}
          value={text}
          placeholder={placeholder}
          autoComplete="off"
          onChange={(e) => {
            setText(e.target.value);
            setOpen(true);
            setActive(-1);
            setProblem(null);
          }}
          onKeyDown={onKeyDown}
          onBlur={() => setOpen(false)}
          className={`${INPUT} ${inputBorder(shownError)}`}
        />
        <ul
          id={listId}
          role="listbox"
          aria-label={`Suggestions for ${label.toLowerCase()}`}
          hidden={!expanded}
          className="absolute inset-x-0 top-full z-10 mt-1 max-h-72 overflow-auto rounded-md border border-rule bg-surface py-1 shadow-sm"
        >
          {options.map((option, i) => (
            <li
              key={option.value}
              id={`${listId}-${i}`}
              role="option"
              aria-selected={i === active}
              onMouseDown={(e) => e.preventDefault()}
              onClick={() => add([option.label])}
              className={`flex min-h-11 cursor-pointer items-center px-3 text-[0.9375rem] ${i === active ? "bg-accent-soft" : "hover:bg-paper"}`}
            >
              {option.label}
            </li>
          ))}
        </ul>
      </div>
      <FieldError id={errorId}>{shownError ?? undefined}</FieldError>
      <p className="sr-only" aria-live="polite">
        {announcement}
      </p>
    </div>
  );
}

// ---- Confirmation dialog -------------------------------------------------------------

type ConfirmDialogProps = {
  title: string;
  children: React.ReactNode;
  confirmLabel: string;
  cancelLabel: string;
  onConfirm: () => void;
  onCancel: () => void;
  tone?: "danger" | "neutral";
};

/**
 * A small modal for "are you sure". Focus starts on the safe choice, Tab stays inside,
 * Escape cancels, and focus returns to whatever opened it.
 */
export function ConfirmDialog({
  title,
  children,
  confirmLabel,
  cancelLabel,
  onConfirm,
  onCancel,
  tone = "neutral",
}: ConfirmDialogProps) {
  const titleId = useId();
  const bodyId = useId();
  const dialogRef = useRef<HTMLDivElement>(null);
  const cancelRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    const opener = document.activeElement as HTMLElement | null;
    cancelRef.current?.focus();
    return () => {
      if (opener && document.contains(opener)) opener.focus();
    };
  }, []);

  function onKeyDown(event: React.KeyboardEvent) {
    if (event.key === "Escape") {
      event.preventDefault();
      onCancel();
    } else if (event.key === "Tab") {
      const buttons = dialogRef.current?.querySelectorAll<HTMLButtonElement>("button");
      if (!buttons || buttons.length === 0) return;
      const first = buttons[0]!;
      const last = buttons[buttons.length - 1]!;
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    }
  }

  const confirmClass =
    tone === "danger"
      ? "border-danger bg-danger text-surface hover:bg-danger/90"
      : "border-accent bg-accent text-surface hover:bg-accent-hover";

  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-ink/30 p-4 sm:items-center">
      <div
        ref={dialogRef}
        role="alertdialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={bodyId}
        onKeyDown={onKeyDown}
        className="w-full max-w-md rounded-lg border border-rule bg-surface p-6"
      >
        <h2 id={titleId} className="font-serif text-2xl font-medium">
          {title}
        </h2>
        <div id={bodyId} className="mt-2 text-[0.9375rem] leading-relaxed text-muted">
          {children}
        </div>
        <div className="mt-6 flex flex-col-reverse gap-3 sm:flex-row sm:justify-end">
          <button
            ref={cancelRef}
            type="button"
            onClick={onCancel}
            className="inline-flex h-11 items-center justify-center rounded-md border border-rule bg-surface px-4 text-sm font-medium hover:border-muted"
          >
            {cancelLabel}
          </button>
          <button
            type="button"
            onClick={onConfirm}
            className={`inline-flex h-11 items-center justify-center rounded-md border px-4 text-sm font-medium ${confirmClass}`}
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}

/** Move focus to a field by id; for a group, to its first control. */
export function focusField(id: string) {
  const el = document.getElementById(id);
  if (!el) return;
  if (el.tagName === "FIELDSET") el.querySelector<HTMLElement>("input, button, select, textarea")?.focus();
  else el.focus();
}

// ---- Error summary -------------------------------------------------------------------

type ErrorSummaryProps = {
  /** Field id (as passed to focusField) -> its label and message, in page order. */
  items: { id: string; label: string; message: string }[];
  /** Bumped on every failed Finish or Save, so focus moves here each time. */
  attempt: number;
};

/**
 * "3 things need fixing" at the top of a form, each a link to its field. It takes focus
 * when shown (and on every new failed attempt), so screen readers hear the count first;
 * the inline errors stay beside each field.
 */
export function ErrorSummary({ items, attempt }: ErrorSummaryProps) {
  const ref = useRef<HTMLDivElement>(null);
  const titleId = useId();
  useEffect(() => {
    if (attempt > 0) ref.current?.focus();
  }, [attempt]);
  if (items.length === 0) return null;
  return (
    <div
      ref={ref}
      tabIndex={-1}
      aria-labelledby={titleId}
      className="rounded-md border border-danger/40 bg-danger-bg px-5 py-4 outline-none focus-visible:outline-2 focus-visible:outline-danger"
    >
      <h2 id={titleId} className="font-serif text-xl font-medium">
        {items.length === 1 ? "1 thing needs fixing" : `${items.length} things need fixing`}
      </h2>
      <ul className="mt-2 space-y-1 text-[0.9375rem]">
        {items.map((item) => (
          <li key={item.id}>
            <a
              href={`#${item.id}`}
              onClick={(event) => {
                event.preventDefault();
                focusField(item.id);
              }}
              className="text-danger underline underline-offset-4"
            >
              {item.label}: {item.message}
            </a>
          </li>
        ))}
      </ul>
    </div>
  );
}
