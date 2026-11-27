import { vi } from "vitest";

/** The one router every component gets in tests, so a test can check where it navigated. */
export const router = { push: vi.fn(), replace: vi.fn(), back: vi.fn() };
