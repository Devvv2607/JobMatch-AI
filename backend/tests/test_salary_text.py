"""Salary from text, including Indian formats, with refusal rules.

"real" cases are verbatim snippets from postings in the pool on 2026-11-24 (public job
text); "synthetic" cases cover formats the pool did not happen to contain.
"""

import pytest

from app.ingest.salary import fx_table, text_salary
from app.ingest.salary_text import parse


def read(text: str, context: bool = True) -> tuple[object, str | None]:
    salary, refusal = text_salary(text, "description", require_context=context)
    if salary is None:
        return None, refusal
    return (salary.min, salary.max, salary.currency, salary.interval), refusal


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        # real
        (
            "and Employee Travel Credits. India Annual Pay Range ₹5,900,000—₹8,500,000 INR "
            "Reasonable Accommodations: We are committed",
            (5_900_000, 8_500_000, "INR", "year"),
        ),
        (
            "Annual base salary range (excluding equity and bonus): ₹4,408,400—₹4,408,400 INR "
            "- Application Limit",
            (4_408_400, 4_408_400, "INR", "year"),
        ),
        (
            "compensation for this role! Salary Range: ₹11,969,600—₹17,954,400 INR Benefits:",
            (11_969_600, 17_954_400, "INR", "year"),
        ),
        (
            "self-service and automation. Compensation Band : INR 90.40L to 1.2Cr Job Benefits:",
            (9_040_000, 12_000_000, "INR", "year"),
        ),
        (
            "office in Pune 4-5 days per week. Compensation Bands: ₹26L – ₹30L • Offers Equity",
            (2_600_000, 3_000_000, "INR", "year"),
        ),
        ("The base salary range is $150,000—$200,000 USD.", (150_000, 200_000, "USD", "year")),
        # synthetic
        ("CTC: 20 LPA", (2_000_000, 2_000_000, "INR", "year")),
        ("Expected CTC: 12-18 LPA", (1_200_000, 1_800_000, "INR", "year")),
        ("Stipend: Rs. 25,000 per month", (25_000, 25_000, "INR", "month")),
        ("Salary: ₹12,00,000 - ₹18,00,000 per annum", (1_200_000, 1_800_000, "INR", "year")),
        ("Package of 15-20 lakhs per annum", (1_500_000, 2_000_000, "INR", "year")),
        ("Salary up to ₹40L", (None, 4_000_000, "INR", "year")),
        ("Pay: $45 - $60 per hour", (45, 60, "USD", "hour")),
    ],
)
def test_salaries_are_read(text: str, expected: tuple[object, ...]) -> None:
    assert read(text) == (expected, None)


@pytest.mark.parametrize(
    "text",
    [
        # real: money that is not pay
        "credit accessible to millions across India. with loan offerings ranging from "
        "₹50,000 to ₹5 Lakh, we’re enabling instant personal loans",
        "family members ● OPD benefit covered up to INR 10,000 ● Life insurance and "
        "personal accident insurance at 3x annual CTC ● 26",
        "Sustain an average ticket size of at least ₹15,000 by prioritising family floater",
        "A track record of consistently hitting quota (typically in the ₹2–5 Cr / "
        "$300K–$750K range) sold through longer",
        "Track record of closing and managing multi-crore engagements",
        "Continuous Transaction Controls (CTC) and e-invoicing mandates",
        # synthetic: no salary word near the amount in description text
        "We raised $20,000,000 - $30,000,000 last year.",
        "2-5 years of experience",
    ],
)
def test_money_that_is_not_pay_is_ignored(text: str) -> None:
    assert read(text) == (None, None)


@pytest.mark.parametrize(
    ("text", "refusal"),
    [
        ("Salary: ₹50,000 - ₹70,000 per month per annum", "mixed_periods"),
        (
            "US pay range $150,000—$200,000 USD. Canada pay range $170,000—$220,000 USD.",
            "multiple_ranges",
        ),
        (
            "The pay range is $150,000-$200,000 in the US; salary in India ₹40,00,000-₹60,00,000.",
            "mixed_currencies",
        ),
        ("Compensation: ₹30L – $50,000", "mixed_currencies"),
        ("Salary: $40 - $60", "no_period"),
        ("Salary: $5,000,000 - $6,000,000", "implausible_amount"),
    ],
)
def test_ambiguous_salaries_are_refused_with_a_reason(text: str, refusal: str) -> None:
    assert read(text) == (None, refusal)


def test_a_salary_field_needs_no_salary_word_but_description_text_does() -> None:
    assert read("$170k - $200k", context=False)[0] == (170_000, 200_000, "USD", "year")
    assert read("$170k - $200k", context=True) == (None, None)


def test_empty_input() -> None:
    assert parse(None, require_context=True, usd_rate=fx_table()[1]).salary is None
    assert parse("", require_context=False, usd_rate=fx_table()[1]).refusal is None
