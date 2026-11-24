"""Salary from free text: deterministic, with refusal rules.

Approach credited to hireplz (MIT, github.com/nishant-Tiwari24/hireplz): extract only
what is unambiguous and refuse the rest rather than guess. The rules and code here are
our own.

A salary is read from text only when
- it has a currency (symbol, code, or an Indian unit: LPA / lakh / crore, which imply INR);
- in description text, a salary word (salary, compensation, pay, CTC, package, stipend,
  base, band, LPA...) appears shortly before or after it, and no non-pay word (quota,
  loan, revenue, ticket size, worth, insurance, benefit...) does;
- its period is stated or can only be one (LPA and lakh / crore amounts are annual; plain
  amounts are annual only when large enough to be nothing else).

It is refused, with a reason, when salary context is present but the figure is
ambiguous: mixed periods, mixed currencies, several different ranges, no period, or an
implausible annual amount. Structured ATS salary always takes precedence over text.

Indian formats: "12-18 LPA", "₹26L – ₹30L", "INR 90.40L to 1.2Cr", "₹12,00,000 - ₹18,00,000",
"Rs. 25,000 per month", "CTC: 20 LPA", "15 lakhs per annum".
"""

import re
from dataclasses import dataclass
from typing import Literal

Refusal = Literal[
    "mixed_periods",
    "mixed_currencies",
    "multiple_ranges",
    "no_period",
    "implausible_amount",
]


@dataclass(frozen=True)
class TextSalary:
    min: float | None
    max: float | None
    currency: str
    interval: str


@dataclass(frozen=True)
class ParsedText:
    salary: TextSalary | None
    refusal: Refusal | None


NOTHING = ParsedText(None, None)

_SYMBOL = {"$": "USD", "€": "EUR", "£": "GBP", "₹": "INR"}
_CODES = "USD|EUR|GBP|INR|CAD|AUD|SGD|CHF|AED|JPY"
_CUR = rf"(?:[$€£₹]|\b(?:{_CODES})\b\.?|\bRs\.?|\bRupees?\b)"
# 1,234,567 / 12,00,000 (Indian grouping) / 120000 / 90.40 / 35,3
_NUM = r"\d{1,3}(?:,\d{2,3})+(?:\.\d+)?|\d+(?:[.,]\d+)?"
_SCALE = r"(?:k\b|K\b|lpa\b|LPA\b|lakhs?\b|lacs?\b|L\b|crores?\b|cr\b|Cr\b|CR\b|mn\b|M\b)"
_AMOUNT = rf"(?:{_CUR}\s*)?(?:{_NUM})\s*{_SCALE}?(?:\s*{_CUR})?"
_RANGE = re.compile(
    rf"(?P<a>{_AMOUNT})\s*(?:-|–|—|to|and)\s*(?P<b>{_AMOUNT})|(?P<single>{_AMOUNT})",
    re.IGNORECASE,
)
_PART = re.compile(
    rf"(?P<cur1>{_CUR})?\s*(?P<num>{_NUM})\s*(?P<scale>{_SCALE})?\s*(?P<cur2>{_CUR})?",
    re.IGNORECASE,
)
_PERIODS = {
    "hour": r"(?:per|an|/|a)\s*(?:hour|hr)\b|hourly\b|/\s*h\b",
    "day": r"(?:per|a|/)\s*day\b|daily\b",
    "week": r"(?:per|a|/)\s*week\b|weekly\b",
    "month": r"(?:per|a|/)\s*(?:month|mo)\b|monthly\b|\bp\.?\s?m\.?(?=\s|$|[,.;)])",
    "year": (
        r"(?:per|a|/)\s*(?:year|yr|annum)\b|annual(?:ly)?\b|yearly\b"
        r"|\bp\.?\s?a\.?(?=\s|$|[,.;)])|\blpa\b"
    ),
}
_PERIOD_RES = {name: re.compile(p, re.IGNORECASE) for name, p in _PERIODS.items()}
_PER_YEAR = {"year": 1, "month": 12, "week": 52, "day": 260, "hour": 2080}
_CONTEXT = re.compile(
    r"\b(?:salar(?:y|ies)|compensation|pay(?:\s*range|\s*band)?|ctc|package|stipend|"
    r"base|band|remuneration|earning|wage|lpa|per\s+annum|ote)\b",
    re.IGNORECASE,
)
_NOT_PAY = re.compile(
    r"\b(?:quota|loans?|revenue|arr|ticket\s+size|worth|insurance|cover(?:ed|age)?|opd|"
    r"funding|raised|valuation|deals?|engagements?|turnover|budget|grant|reimburs\w*|"
    r"allowance|credit|claims?|bonus\s+pool|prize)\b",
    re.IGNORECASE,
)
_WINDOW = 80
# Annual USD outside this is a misread (a monthly figure read as annual, a revenue line).
_PLAUSIBLE_USD = (1_000, 2_000_000)


def parse(text: str | None, *, require_context: bool, usd_rate: dict[str, float]) -> ParsedText:
    """`require_context=False` for a field that is a salary by definition (an ATS's
    salary text); `True` for free description text."""
    if not text:
        return NOTHING
    found: list[tuple[TextSalary, str]] = []
    refusals: list[Refusal] = []
    for match in _RANGE.finditer(text):
        span = match.group(0)
        if not re.search(r"\d", span):
            continue
        before = text[max(0, match.start() - _WINDOW) : match.start()]
        after = text[match.end() : match.end() + _WINDOW]
        near = f"{before} {after}"
        if require_context and not _CONTEXT.search(near + " " + span):
            continue
        if _NOT_PAY.search(before[-50:] + " " + after[:30]):
            continue
        result = _read(match, before, after, usd_rate)
        if result is None:
            continue
        if isinstance(result, str):
            refusals.append(result)
        else:
            found.append((result, span))

    distinct = {(s.min, s.max, s.currency, s.interval) for s, _ in found}
    if len(distinct) > 1:
        currencies = {s.currency for s, _ in found}
        return ParsedText(None, "mixed_currencies" if len(currencies) > 1 else "multiple_ranges")
    if found:
        return ParsedText(found[0][0], None)
    if refusals:
        return ParsedText(None, refusals[0])
    return NOTHING


def _read(
    match: re.Match[str], before: str, after: str, usd_rate: dict[str, float]
) -> TextSalary | Refusal | None:
    single = match.group("single")
    parts = [p for p in ((single,) if single else (match.group("a"), match.group("b"))) if p]
    parsed = [_PART.fullmatch(p.strip()) for p in parts]
    if any(p is None for p in parsed):
        return None
    pieces = [p for p in parsed if p is not None]
    currencies = {_currency(p.group("cur1") or p.group("cur2")) for p in pieces} - {None}
    scales = [(p.group("scale") or "").lower() for p in pieces]
    indian_unit = any(s.startswith(("lpa", "lakh", "lac", "l", "cr")) for s in scales)
    if indian_unit:
        currencies |= {"INR"}
    if not currencies:
        return None  # no currency: a count, a year, an experience range
    if len(currencies) > 1:
        return "mixed_currencies"
    (currency,) = currencies
    if currency not in usd_rate:
        return None

    # A scale written once applies to both ends: "12-18 LPA", "$170-200k".
    shared = next((s for s in reversed(scales) if s), "")
    values = [_value(p.group("num"), s or shared) for p, s in zip(pieces, scales, strict=True)]
    if any(v is None or v <= 0 for v in values):
        return None
    low, high = (values[0], values[-1]) if len(values) == 2 else (values[0], values[0])
    assert low is not None and high is not None  # noqa: S101  # checked above
    if low > high:
        low, high = high, low
    if single and not _looks_like_salary_single(before, after):
        return None

    near = f"{match.group(0)} {after[:40]}"
    periods = {name for name, rx in _PERIOD_RES.items() if rx.search(near)}
    if any(s.startswith("lpa") for s in scales):
        periods.add("year")
    if len(periods) > 1:
        return "mixed_periods"
    if periods:
        (interval,) = periods
    elif (
        indian_unit
        or high * usd_rate[currency] >= 10_000
        or (currency == "INR" and high >= 300_000)
    ):
        interval = "year"
    else:
        return "no_period"

    annual_usd = high * _PER_YEAR[interval] * usd_rate[currency]
    if not _PLAUSIBLE_USD[0] <= annual_usd <= _PLAUSIBLE_USD[1]:
        return "implausible_amount"
    if single:
        upto = re.search(r"\b(?:up\s*to|upto|max(?:imum)?)\s*$", before, re.IGNORECASE)
        return TextSalary(None if upto else low, high, currency, interval)
    return TextSalary(low, high, currency, interval)


def _looks_like_salary_single(before: str, after: str) -> bool:
    """A lone amount counts only right after a salary word ("CTC: 20 LPA", "Salary up to
    $120k"), never just somewhere nearby."""
    return bool(
        re.search(
            r"(?:salary|compensation|ctc|package|stipend|pay|base|remuneration)"
            r"[^.\n]{0,25}$",
            before,
            re.IGNORECASE,
        )
    )


def _currency(token: str | None) -> str | None:
    if not token:
        return None
    token = token.strip().rstrip(".").upper()
    if token in ("RS", "RUPEE", "RUPEES"):
        return "INR"
    return _SYMBOL.get(token, token)


def _value(number: str, scale: str) -> float | None:
    digits = number.replace(" ", "")
    if re.fullmatch(r"\d{1,3}(?:,\d{2,3})+(?:\.\d+)?", digits):
        value = float(digits.replace(",", ""))
    elif re.fullmatch(r"\d+,\d{1,2}", digits):  # "35,3k": a decimal comma
        value = float(digits.replace(",", "."))
    else:
        try:
            value = float(digits)
        except ValueError:
            return None
    scale = scale.lower()
    if scale == "k":
        value *= 1_000
    elif scale in ("m", "mn"):
        value *= 1_000_000
    elif scale.startswith(("lpa", "lakh", "lac")) or scale == "l":
        value *= 100_000
    elif scale.startswith(("crore", "cr")):
        value *= 10_000_000
    return value
