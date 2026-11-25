"""Salary normalisation to annual USD with the dated table in data/fx_rates.yaml.

The original amount, currency and interval are kept; only the *_usd columns are
converted. Text salaries are parsed by app/ingest/salary_text.py, which refuses (with a
reason) anything ambiguous rather than guessing. Precedence: structured ATS salary, then
the ATS salary text field, then the description.

INR amounts labelled annual go through salary_text.inr_annual_check for structured
salaries too (Adzuna and Himalayas label monthly pay as annual: "INR 20,000-40,000 per
year"): below 1.5 lakh, monthly only if a description line holding the same figure says
so, otherwise refused (implausible_amount); above 10 crore, refused.
"""

import re
from dataclasses import dataclass
from functools import cache
from pathlib import Path

import yaml

from app.ingest import salary_text
from app.ingest.types import RawSalary

_DATA = Path(__file__).parent / "data" / "fx_rates.yaml"
_PER_YEAR = {"year": 1, "month": 12, "week": 52, "day": 260, "hour": 2080}


@dataclass(frozen=True)
class Salary:
    min: float | None
    max: float | None
    currency: str
    interval: str
    min_usd: int | None
    max_usd: int | None
    source: str


@cache
def fx_table() -> tuple[str, dict[str, float]]:
    raw = yaml.safe_load(_DATA.read_text(encoding="utf-8"))
    per_eur = {code: float(rate) for code, rate in raw["per_eur"].items()}
    usd_per_eur = per_eur["USD"]
    return str(raw["date"]), {code: usd_per_eur / rate for code, rate in per_eur.items()}


def to_annual_usd(amount: float | None, currency: str, interval: str) -> int | None:
    if amount is None or amount <= 0:
        return None
    rate = fx_table()[1].get(currency.upper())
    multiplier = _PER_YEAR.get(interval)
    if rate is None or multiplier is None:
        return None
    return round(amount * multiplier * rate)


def from_structured(raw: RawSalary, source: str) -> Salary | None:
    return structured_salary(raw, source)[0]


def structured_salary(
    raw: RawSalary, source: str, description: str | None = None
) -> tuple[Salary | None, str | None]:
    """(salary, refusal reason) for a source's structured salary."""
    low, high = _ordered(raw.min, raw.max)
    interval = raw.interval
    top = high if high is not None else low
    if raw.currency.upper() == "INR" and interval == "year" and top:
        lines = _lines_with_figure(description or "", [v for v in (low, high) if v])
        refused, interval = salary_text.inr_annual_check(top, "\n".join(lines))
        if refused:
            return None, "implausible_amount"
    salary = Salary(
        min=low,
        max=high,
        currency=raw.currency.upper(),
        interval=interval,
        min_usd=to_annual_usd(low, raw.currency, interval),
        max_usd=to_annual_usd(high, raw.currency, interval),
        source=source,
    )
    return (salary, None) if salary.min_usd or salary.max_usd else (None, None)


_FIGURE = re.compile(r"\d[\d,]*(?:\.\d+)?\s*[kK]?\b")


def _lines_with_figure(text: str, figures: list[float]) -> list[str]:
    """Lines of `text` that write one of `figures` (20000, 20,000, 2,00,000, 20k)."""
    wanted = {round(f) for f in figures}
    found = []
    for line in text.splitlines():
        for m in _FIGURE.finditer(line):
            token = m.group(0).replace(",", "").strip()
            scale = 1000 if token[-1] in "kK" else 1
            try:
                value = float(token.rstrip("kK").strip()) * scale
            except ValueError:
                continue
            if round(value) in wanted:
                found.append(line)
                break
    return found


def from_text(text: str | None, source: str) -> Salary | None:
    """Salary from a field that is a salary by definition (an ATS salary text)."""
    return text_salary(text, source, require_context=False)[0]


def text_salary(
    text: str | None, source: str, *, require_context: bool
) -> tuple[Salary | None, str | None]:
    """(salary, refusal reason). See app/ingest/salary_text.py for the rules."""
    parsed = salary_text.parse(text, require_context=require_context, usd_rate=fx_table()[1])
    if parsed.salary is None:
        return None, parsed.refusal
    found = parsed.salary
    salary = from_structured(
        RawSalary(found.min, found.max, found.currency, found.interval), source
    )
    return salary, None if salary else "implausible_amount"


def _ordered(low: float | None, high: float | None) -> tuple[float | None, float | None]:
    if low is not None and high is not None and low > high:
        return high, low
    return low, high
