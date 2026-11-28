/**
 * The one exchange rate the browser uses: Indian rupees per US dollar, to turn a minimum
 * salary entered in lakhs a year (LPA) into the US dollars a year the API's
 * `min_salary_usd` rule takes.
 *
 * It is the rate the backend uses to convert posting salaries
 * (backend/app/ingest/data/fx_rates.yaml: ECB reference rates, INR 103.4520 and
 * USD 1.1014 per EUR, published 2026-11-16), so a minimum and a posting are converted
 * the same way. A test fails if the backend table changes and this does not.
 *
 * Fixed on purpose, like the backend table: filters must be reproducible. In 5c the
 * backend takes the currency itself and the rate becomes configurable there.
 */
export const INR_PER_USD = { rate: 93.93, asOf: "2026-11-16", source: "ECB reference rates via fx_rates.yaml" } as const;

export const LAKH = 100_000;

export type SalaryCurrency = "INR" | "USD";

/** Whole US dollars a year for an amount in LPA (INR) or US dollars a year (USD). */
export function toUsdPerYear(amount: number, currency: SalaryCurrency): number {
  return currency === "USD" ? Math.round(amount) : Math.round((amount * LAKH) / INR_PER_USD.rate);
}

/** "≈ $8,517/yr" */
export function usdHint(usd: number): string {
  return `≈ $${usd.toLocaleString("en-US")}/yr`;
}
