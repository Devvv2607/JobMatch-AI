"use client";

import { useSyncExternalStore } from "react";

import { clearFeedback } from "../feedback";
import { isStoredProfile, type StoredProfile } from "./model";

/** The profile lives in this browser until accounts store it (5c). */
export const PROFILE_KEY = "jobmatch.profile.v1";

export type ProfileState =
  | { status: "empty" }
  | { status: "ready"; stored: StoredProfile }
  /** Something is stored but can't be read: storage blocked, or the data is damaged. */
  | { status: "error"; reason: "unreadable" | "damaged" };

const listeners = new Set<() => void>();
const EMPTY: ProfileState = { status: "empty" };
let cache: { raw: string | null | undefined; value: ProfileState } = { raw: undefined, value: EMPTY };

/** The cache key after a storage error: matches no real value, so the next read starts over. */
const UNREADABLE = "\u0000unreadable";

export function readProfile(): ProfileState {
  if (typeof window === "undefined") return EMPTY;
  let raw: string | null;
  try {
    raw = window.localStorage.getItem(PROFILE_KEY);
  } catch {
    if (cache.raw !== UNREADABLE) cache = { raw: UNREADABLE, value: { status: "error", reason: "unreadable" } };
    return cache.value;
  }
  if (raw === cache.raw) return cache.value;
  let value: ProfileState = EMPTY;
  if (raw) {
    try {
      const parsed: unknown = JSON.parse(raw);
      value = isStoredProfile(parsed) ? { status: "ready", stored: parsed } : { status: "error", reason: "damaged" };
    } catch {
      value = { status: "error", reason: "damaged" };
    }
  }
  cache = { raw, value };
  return value;
}

function notify() {
  listeners.forEach((listener) => listener());
}

/** False when the browser refused (storage full or blocked); the caller says so. */
export function writeProfile(stored: StoredProfile): boolean {
  try {
    window.localStorage.setItem(PROFILE_KEY, JSON.stringify(stored));
  } catch {
    return false;
  }
  notify();
  return true;
}

/** "Clear my data": the profile and the saved / not-for-me marks. */
export function clearMyData(): boolean {
  let ok = true;
  try {
    window.localStorage.removeItem(PROFILE_KEY);
  } catch {
    ok = false;
  }
  if (!clearFeedback()) ok = false;
  notify();
  return ok;
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  const onStorage = (event: StorageEvent) => {
    if (event.key === PROFILE_KEY || event.key === null) listener();
  };
  window.addEventListener("storage", onStorage);
  return () => {
    listeners.delete(listener);
    window.removeEventListener("storage", onStorage);
  };
}

/** `null` while rendering on the server, so nothing flashes before the browser is read. */
export function useStoredProfile(): ProfileState | null {
  return useSyncExternalStore<ProfileState | null>(subscribe, readProfile, () => null);
}
