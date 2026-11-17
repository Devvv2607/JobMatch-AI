import createClient from "openapi-fetch";

import type { components, paths } from "./api-types";

export type User = components["schemas"]["UserOut"];
export type Session = components["schemas"]["SessionOut"];
type ErrorEnvelope = components["schemas"]["ErrorEnvelope"];

export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

/** Typed client generated from the backend's OpenAPI schema. Sends cookies so the
 * httpOnly refresh cookie reaches /auth endpoints. */
export const api = createClient<paths>({ baseUrl: API_URL, credentials: "include" });

/** Required by the backend on endpoints that read the refresh cookie (CSRF guard). */
export const CSRF_HEADERS = { "x-requested-with": "jobmatch" } as const;

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly code: string,
    readonly fields: Record<string, string> = {},
  ) {
    super(message);
  }
}

const FRIENDLY_FIELD_MESSAGES: Record<string, string> = {
  value_error: "Enter a valid email address.",
  string_too_short: "Use at least 10 characters.",
  string_too_long: "Use at most 128 characters.",
};

/** Turns the backend's error envelope into an ApiError with per-field messages. */
export function toApiError(error: unknown, response: Response): ApiError {
  const envelope = (error as ErrorEnvelope | undefined)?.error;
  if (!envelope) {
    return new ApiError("Something went wrong. Try again.", response.status, "unknown");
  }
  const fields: Record<string, string> = {};
  for (const detail of envelope.details ?? []) {
    const field = String(detail.field ?? "").split(".").pop();
    const type = String(detail.type ?? "");
    if (field && !fields[field]) {
      fields[field] = FRIENDLY_FIELD_MESSAGES[type] ?? String(detail.message ?? "Check this field.");
    }
  }
  return new ApiError(envelope.message, response.status, envelope.code, fields);
}

/** Network failures (API down, CORS) never reach the envelope path. */
export function networkError(): ApiError {
  return new ApiError("Can't reach the server. Check your connection and try again.", 0, "network");
}
