"use client";

import { useEffect, useId, useRef, useState } from "react";

import { Button } from "@/components/button";
import { DISMISS_REASONS, type DismissReason } from "@/lib/types";

export const REASON_LABELS: Record<DismissReason, string> = {
  wrong_level: "Wrong level",
  location: "Location doesn't work",
  salary: "Salary too low",
  company: "Not interested in this company",
  other: "Something else",
};

type Props = {
  jobTitle: string;
  saved: boolean;
  onSave: () => void;
  onUnsave: () => void;
  onDismiss: (reason: DismissReason, note: string | null) => void;
  sourceUrl: string;
  sourceName: string;
};

export function FeedbackControls({ jobTitle, saved, onSave, onUnsave, onDismiss, sourceUrl, sourceName }: Props) {
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState<DismissReason | null>(null);
  const [note, setNote] = useState("");
  const triggerRef = useRef<HTMLButtonElement>(null);
  const panelRef = useRef<HTMLFieldSetElement>(null);
  const panelId = useId();
  const noteId = useId();

  useEffect(() => {
    if (open) panelRef.current?.querySelector<HTMLInputElement>("input")?.focus();
  }, [open]);

  function close() {
    setOpen(false);
    setReason(null);
    setNote("");
    triggerRef.current?.focus();
  }

  function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!reason) return;
    onDismiss(reason, reason === "other" ? note.trim() || null : null);
  }

  return (
    <div className="mt-6">
      <div className="flex flex-wrap items-center gap-3">
        <Button
          variant={saved ? "primary" : "quiet"}
          aria-pressed={saved}
          onClick={saved ? onUnsave : onSave}
          className="min-w-24"
        >
          {saved ? "Saved" : "Save"}
          <span className="sr-only">: {jobTitle}</span>
        </Button>
        <Button
          ref={triggerRef}
          variant="quiet"
          aria-expanded={open}
          aria-controls={panelId}
          onClick={() => (open ? close() : setOpen(true))}
        >
          Not for me<span className="sr-only">: {jobTitle}</span>
        </Button>
        <a
          href={sourceUrl}
          target="_blank"
          rel="noopener noreferrer"
          className="ml-auto inline-flex h-11 items-center text-sm text-accent underline decoration-rule underline-offset-4 hover:decoration-accent"
        >
          View on {sourceName}
          <span aria-hidden="true">&nbsp;↗</span>
          <span className="sr-only"> (opens in a new tab)</span>
        </a>
      </div>

      {open && (
        <form onSubmit={submit} className="mt-4">
          <fieldset
            ref={panelRef}
            id={panelId}
            onKeyDown={(event) => {
              if (event.key === "Escape") {
                event.stopPropagation();
                close();
              }
            }}
            className="rounded-md border border-rule bg-surface p-4"
          >
            <legend className="px-1 text-sm font-medium">Why isn’t this one for you?</legend>
            <p className="mb-3 px-1 text-sm text-muted">It helps tomorrow’s list. Kept on this device only.</p>
            <div className="grid gap-1 sm:grid-cols-2">
              {DISMISS_REASONS.map((value) => (
                <label
                  key={value}
                  className="flex min-h-11 cursor-pointer items-center gap-3 rounded-sm px-2 text-sm hover:bg-paper"
                >
                  <input
                    type="radio"
                    name={`${panelId}-reason`}
                    value={value}
                    checked={reason === value}
                    onChange={() => setReason(value)}
                    className="size-4 accent-accent"
                  />
                  {REASON_LABELS[value]}
                </label>
              ))}
            </div>
            {reason === "other" && (
              <div className="mt-3 flex flex-col gap-1.5 px-1">
                <label htmlFor={noteId} className="text-sm">
                  What’s wrong with it? <span className="text-muted">(optional)</span>
                </label>
                <input
                  id={noteId}
                  type="text"
                  maxLength={200}
                  value={note}
                  onChange={(event) => setNote(event.target.value)}
                  className="h-11 rounded-md border border-rule bg-paper px-3 text-base outline-none hover:border-muted focus-visible:border-accent"
                />
              </div>
            )}
            <div className="mt-4 flex gap-3 px-1">
              <Button type="submit" disabled={!reason}>
                Hide this job
              </Button>
              <Button type="button" variant="quiet" onClick={close}>
                Cancel
              </Button>
            </div>
          </fieldset>
        </form>
      )}
    </div>
  );
}
