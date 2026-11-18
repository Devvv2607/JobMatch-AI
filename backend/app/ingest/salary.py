"""Salary normalisation to annual USD with the dated table in data/fx_rates.yaml.

The original amount, currency and interval are kept; only the *_usd columns are
converted. Text salaries are parsed conservatively: anything ambiguous is left empty
rather than guessed.
"""

import re
from dataclasses import dataclass
from functools import cache
from pathlib import Path

import yaml

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
    low, high = _ordered(raw.min, raw.max)
    salary = Salary(
        min=low,
        max=high,
        currency=raw.currency.upper(),
        interval=raw.interval,
        min_usd=to_annual_usd(low, raw.currency, raw.interval),
        max_usd=to_annual_usd(high, raw.currency, raw.interval),
        source=source,
    )
    return salary if salary.min_usd or salary.max_usd else None


_SYMBOLS = {"$": "USD", "€": "EUR", "£": "GBP", "₹": "INR"}
_CODES = "USD|EUR|GBP|INR|CAD|AUD|SGD|CHF"
_NUMBER = r"(\d{1,3}(?:[,.]\d{3})+|\d+(?:[.,]\d+)?)\s*([kK]|lpa|LPA|lakhs?|L\b)?"
_RANGE = re.compile(
    rf"(?P<cur1>[$€£₹]|\b(?:{_CODES})\s*)?\s*{_NUMBER}\s*(?:-|–|—|to)\s*"
    rf"(?P<cur2>[$€£₹]|\b(?:{_CODES})\s*)?\s*{_NUMBER}"
    rf"(?:\s*(?P<code>{_CODES})\b)?(?:\s*(?:/|per|an?)\s*(?P<interval>hour|hr|month|mo|year|yr|annum|week|day))?",
    re.I,
)


def from_text(text: str | None, source: str) -> Salary | None:
    """Parses "$170k - $200k", "€60,000–€75,000", "$14 - $20/hour", "12-18 LPA".
    Single amounts and anything without a currency are ignored."""
    if not text:
        return None
    match = _RANGE.search(text)
    if match is None:
        return None
    groups = match.groups()
    cur = match.group("cur1") or match.group("cur2") or match.group("code") or ""
    # A suffix written once applies to both ends: "12-18 LPA", "$170-200k".
    low_suffix, high_suffix = groups[2] or groups[5], groups[5] or groups[2]
    low = _amount(groups[1], low_suffix)
    high = _amount(groups[4], high_suffix)
    lakhs = any(s and s.lower().startswith(("lpa", "lakh", "l")) for s in (groups[2], groups[5]))
    currency = "INR" if lakhs else _SYMBOLS.get(cur.strip(), cur.strip().upper())
    if not currency or currency not in fx_table()[1] or low is None or high is None:
        return None
    interval = _interval(match.group("interval"), low, lakhs)
    if interval is None:
        return None
    return from_structured(RawSalary(low, high, currency, interval), source)


def _amount(number: str | None, suffix: str | None) -> float | None:
    if number is None:
        return None
    if re.fullmatch(r"\d{1,3}(?:[,.]\d{3})+", number):
        value = float(re.sub(r"[,.]", "", number))
    else:
        value = float(number.replace(",", "."))
    suffix = (suffix or "").lower()
    if suffix == "k":
        value *= 1_000
    elif suffix.startswith(("lpa", "lakh", "l")):
        value *= 100_000
    return value


def _interval(word: str | None, low: float, lakhs: bool) -> str | None:
    if lakhs:
        return "year"
    if word:
        word = word.lower()
        return {"hr": "hour", "mo": "month", "yr": "year", "annum": "year"}.get(word, word)
    # No interval given: only amounts that can only be annual are accepted.
    return "year" if low >= 10_000 else None


def _ordered(low: float | None, high: float | None) -> tuple[float | None, float | None]:
    if low is not None and high is not None and low > high:
        return high, low
    return low, high
