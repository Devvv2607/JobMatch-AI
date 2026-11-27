import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach, vi } from "vitest";

import { router } from "./src/test/router";

afterEach(() => {
  cleanup();
  window.localStorage.clear();
  router.push.mockReset();
  router.replace.mockReset();
  router.back.mockReset();
});

vi.mock("next/navigation", async () => {
  const { router } = await import("./src/test/router");
  return { useRouter: () => router };
});
