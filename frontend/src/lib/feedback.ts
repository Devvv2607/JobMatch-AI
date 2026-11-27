"use client";

import { useCallback, useSyncExternalStore } from "react";

import type { DismissReason, JobFeedback } from "./types";

/** Saved / Not for me, kept on this device until 5c adds the feedback API. */
export const FEEDBACK_KEY = "jobmatch.feedback.v1";

type FeedbackMap = Record<string, JobFeedback>;

const listeners = new Set<() => void>();
let cache: { raw: string | null; value: FeedbackMap } = { raw: null, value: {} };

function read(): FeedbackMap {
  if (typeof window === "undefined") return {};
  let raw: string | null = null;
  try {
    raw = window.localStorage.getItem(FEEDBACK_KEY);
  } catch {
    return cache.value;
  }
  if (raw === cache.raw) return cache.value;
  let value: FeedbackMap = {};
  try {
    const parsed: unknown = raw ? JSON.parse(raw) : {};
    if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) value = parsed as FeedbackMap;
  } catch {
    value = {};
  }
  cache = { raw, value };
  return value;
}

function write(next: FeedbackMap) {
  try {
    window.localStorage.setItem(FEEDBACK_KEY, JSON.stringify(next));
  } catch {
    // Storage full or blocked: keep it in memory for this session.
    cache = { raw: cache.raw, value: next };
  }
  listeners.forEach((listener) => listener());
}

/** Forget every saved / not-for-me mark (part of "Clear my data"). False if storage refused. */
export function clearFeedback(): boolean {
  let ok = true;
  try {
    window.localStorage.removeItem(FEEDBACK_KEY);
  } catch {
    ok = false;
  }
  cache = { raw: null, value: {} };
  listeners.forEach((listener) => listener());
  return ok;
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  const onStorage = (event: StorageEvent) => {
    if (event.key === FEEDBACK_KEY) listener();
  };
  window.addEventListener("storage", onStorage);
  return () => {
    listeners.delete(listener);
    window.removeEventListener("storage", onStorage);
  };
}

const EMPTY: FeedbackMap = {};

export function useJobFeedback(jobId: string) {
  const all = useSyncExternalStore(subscribe, read, () => EMPTY);
  const current = all[jobId] ?? null;

  const save = useCallback(() => {
    write({
      ...read(),
      [jobId]: { job_id: jobId, action: "saved", reason: null, note: null, created_at: new Date().toISOString() },
    });
  }, [jobId]);

  const dismiss = useCallback(
    (reason: DismissReason, note: string | null) => {
      write({
        ...read(),
        [jobId]: {
          job_id: jobId,
          action: "dismissed",
          reason,
          note: reason === "other" && note ? note.slice(0, 200) : null,
          created_at: new Date().toISOString(),
        },
      });
    },
    [jobId],
  );

  const clear = useCallback(() => {
    const next = { ...read() };
    delete next[jobId];
    write(next);
  }, [jobId]);

  return { current, save, dismiss, clear };
}
