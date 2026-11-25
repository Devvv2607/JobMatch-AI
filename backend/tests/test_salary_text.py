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
        # Both periods and an amount plausible either way: refused. (₹50,000-70,000 "per
        # month per annum" is now read as monthly: as annual it is below 1.5 lakh.)
        ("Salary: ₹5,00,000 - ₹7,00,000 per month per annum", "mixed_periods"),
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


# INR plausibility (owner rule 2026-11-25): an annual INR figure below 1.5 lakh is monthly
# only with a monthly marker on the same line, otherwise refused; above 10 crore, refused.


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        # A monthly marker on the same line turns a too-small "annual" figure into monthly.
        (
            "Salary: INR 20,000-40,000 per year, i.e. paid as a fixed amount per month",
            (20_000, 40_000, "INR", "month"),
        ),
        ("Stipend: Rs. 15,000 - 25,000 per month for six months", (15_000, 25_000, "INR", "month")),
        ("Salary: INR 30,000-45,000 p.m.", (30_000, 45_000, "INR", "month")),
        # Plausible annual figures are untouched.
        ("CTC: 1.5 - 3 LPA", (150_000, 300_000, "INR", "year")),
        ("Salary: ₹3,00,000 - ₹4,50,000 per annum", (300_000, 450_000, "INR", "year")),
    ],
)
def test_inr_monthly_marker_on_the_line_annualises(text: str, expected: tuple[object, ...]) -> None:
    assert read(text) == (expected, None)


@pytest.mark.parametrize(
    "text",
    [
        "Salary: INR 20,000-40,000 per year",
        # The monthly marker is on another line: not evidence for this figure.
        "Salary: INR 90,000-1,20,000 per year\nTeam lunches every month, paid monthly reviews",
        "Salary Range: 50K to 1 Lac",  # 1 lakh with no period: likely monthly, not guessed
        # LPA says per annum: never re-read as monthly, even with a marker on the line.
        "CTC: 1 - 1.2 LPA for freshers who clear the training, salary credited per month",
        "Salary: INR 12 crore - 15 crore per annum",
    ],
)
def test_implausible_inr_annual_figures_are_refused(text: str) -> None:
    assert read(text) == (None, "implausible_amount")


def test_inr_rule_also_reads_structured_salaries() -> None:
    from app.ingest.salary import structured_salary
    from app.ingest.types import RawSalary

    labelled_annual = RawSalary(20_000, 40_000, "INR", "year")  # Adzuna, 2026-11-25
    assert structured_salary(labelled_annual, "adzuna.salary", "Great team.") == (
        None,
        "implausible_amount",
    )
    monthly, refusal = structured_salary(
        labelled_annual, "adzuna.salary", "Perks: gym\nSalary 20,000 - 40,000 per month\n"
    )
    assert refusal is None and monthly is not None
    assert (monthly.interval, monthly.max_usd) == ("month", round(480_000 * fx_table()[1]["INR"]))
    # The same marker on a line without the figure does not count.
    assert (
        structured_salary(labelled_annual, "adzuna.salary", "Salary 20k\nPaid monthly")[0] is None
    )
    # 20k on the marked line is the same figure.
    assert structured_salary(labelled_annual, "adzuna.salary", "Pay 20k-40k/month")[1] is None
    big = RawSalary(150_000_000, 200_000_000, "INR", "year")
    assert structured_salary(big, "himalayas.salary", "") == (None, "implausible_amount")
    usd = RawSalary(20_000, 40_000, "USD", "year")
    assert structured_salary(usd, "adzuna.salary", "")[0] is not None


def test_stored_rows_are_rechecked_without_refetching() -> None:
    from app.ingest.normalise import stored_salary
    from app.ingest.types import RawSalary

    adzuna = RawSalary(20_000.0, 40_000.0, "INR", "year")
    assert stored_salary("adzuna.salary", adzuna, "Great team.") == (None, "implausible_amount")
    # A refused structured salary falls back to the description, as at ingest.
    salary, refusal = stored_salary("adzuna.salary", adzuna, "CTC: 4 - 6 LPA")
    assert refusal is None and salary is not None
    assert (salary.min, salary.max, salary.interval, salary.source) == (
        400_000,
        600_000,
        "year",
        "description",
    )
    # A plausible stored salary is unchanged.
    fine = RawSalary(600_000.0, 900_000.0, "INR", "year")
    salary, _ = stored_salary("himalayas.salary", fine, "")
    assert salary is not None and (salary.min, salary.interval) == (600_000, "year")
