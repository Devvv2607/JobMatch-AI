"""Dealbreakers against the database: what each rule keeps, flags and rules out, and that
the filter, the labels and the counts always agree."""

import itertools
import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.retrieval.filters import allowed_ids, outcomes, pool_counts
from app.retrieval.rules import (
    EmploymentTypeRule,
    ExcludeCompanies,
    ExcludeIndustries,
    MinSalary,
    Rule,
    SeniorityRule,
    WorkEligibility,
    WorkplaceRule,
)
from tests.search_helpers import add_company, add_job


@pytest.fixture
async def pool(session: AsyncSession) -> dict[str, uuid.UUID]:
    bank = await add_company(session, "Fin Bank", industries=["fintech"])
    shop = await add_company(session, "Shop Co", industries=["ecommerce"])
    mystery = await add_company(session, "Mystery Inc")
    jobs = {
        "worldwide_remote_rich": await add_job(
            session, shop, "Backend Engineer", salary_min_usd=90_000, salary_max_usd=130_000
        ),
        "india_hybrid_no_salary": await add_job(
            session,
            shop,
            "Data Engineer",
            remote_policy="hybrid",
            eligibility_scope="listed",
            work_countries=["IN"],
        ),
        "us_onsite_fintech": await add_job(
            session,
            bank,
            "Senior Engineer",
            seniority="senior",
            remote_policy="onsite",
            eligibility_scope="listed",
            work_countries=["US"],
            salary_min_usd=150_000,
        ),
        "unknown_everything": await add_job(
            session,
            mystery,
            "Engineer",
            remote_policy="unknown",
            eligibility_scope="unknown",
            employment_type="contract",
        ),
        "low_pay_intern": await add_job(
            session,
            shop,
            "Intern",
            seniority="intern",
            salary_max_usd=20_000,
            employment_type="internship",
        ),
    }
    # Never in the pool, whatever the rules.
    await add_job(session, shop, "Expired", status="expired")
    original = jobs["worldwide_remote_rich"]
    await add_job(session, shop, "Backend Engineer copy", duplicate_of=original.id)
    await session.commit()
    return {name: job.id for name, job in jobs.items()}


def names(ids: set[uuid.UUID], pool: dict[str, uuid.UUID]) -> set[str]:
    by_id = {v: k for k, v in pool.items()}
    return {by_id[i] for i in ids}


@pytest.mark.parametrize(
    ("rule", "kept", "flagged"),
    [
        (
            WorkEligibility(country="India"),
            {
                "worldwide_remote_rich",
                "india_hybrid_no_salary",
                "unknown_everything",
                "low_pay_intern",
            },
            {"unknown_everything"},
        ),
        (
            WorkEligibility(country="IN", strict=True),
            {"worldwide_remote_rich", "india_hybrid_no_salary", "low_pay_intern"},
            set(),
        ),
        (
            WorkplaceRule(allowed=["remote", "hybrid"]),
            {
                "worldwide_remote_rich",
                "india_hybrid_no_salary",
                "unknown_everything",
                "low_pay_intern",
            },
            {"unknown_everything"},
        ),
        (
            MinSalary(amount=100_000),
            {
                "worldwide_remote_rich",
                "india_hybrid_no_salary",
                "us_onsite_fintech",
                "unknown_everything",
            },
            {"india_hybrid_no_salary", "unknown_everything"},
        ),
        (
            MinSalary(amount=100_000, strict=True),
            {"worldwide_remote_rich", "us_onsite_fintech"},
            set(),
        ),
        (
            SeniorityRule(allowed=["mid", "senior"]),
            {
                "worldwide_remote_rich",
                "india_hybrid_no_salary",
                "us_onsite_fintech",
                "unknown_everything",
            },
            set(),
        ),
        (
            EmploymentTypeRule(allowed=["full_time"]),
            {"worldwide_remote_rich", "india_hybrid_no_salary", "us_onsite_fintech"},
            set(),
        ),
        (
            ExcludeIndustries(industries=["FinTech"]),
            {
                "worldwide_remote_rich",
                "india_hybrid_no_salary",
                "unknown_everything",
                "low_pay_intern",
            },
            {"unknown_everything"},
        ),
        (
            ExcludeCompanies(companies=["shop co"]),
            {"us_onsite_fintech", "unknown_everything"},
            set(),
        ),
    ],
)
async def test_each_rule_keeps_flags_and_rules_out(
    session: AsyncSession, pool: dict[str, uuid.UUID], rule: Rule, kept: set[str], flagged: set[str]
) -> None:
    assert names(set(await allowed_ids(session, [rule])), pool) == kept
    labels = await outcomes(session, [rule], list(pool.values()))
    assert names({i for i, r in labels.items() if r[0].flags}, pool) == flagged
    assert names({i for i, r in labels.items() if r[0].excludes}, pool) == set(pool) - kept


async def test_expired_and_duplicate_jobs_are_never_in_the_pool(
    session: AsyncSession, pool: dict[str, uuid.UUID]
) -> None:
    assert set(await allowed_ids(session, [])) == set(pool.values())
    counts = await pool_counts(session, [])
    assert (counts.pool, counts.allowed) == (5, 5)


RULE_SETS: list[Rule] = [
    WorkEligibility(country="IN"),
    WorkplaceRule(allowed=["remote"], strict=True),
    MinSalary(amount=50_000),
    ExcludeIndustries(industries=["fintech"], strict=True),
    EmploymentTypeRule(allowed=["full_time", "contract"]),
]


@pytest.mark.parametrize("size", [1, 2, 3, 5])
async def test_filter_labels_and_counts_agree_for_every_combination(
    session: AsyncSession, pool: dict[str, uuid.UUID], size: int
) -> None:
    for combo in itertools.combinations(RULE_SETS, size):
        rules = list(combo)
        kept = set(await allowed_ids(session, rules))
        labels = await outcomes(session, rules, list(pool.values()))
        excluded_by_labels = {
            i for i, results in labels.items() if any(r.excludes for r in results)
        }
        assert kept == set(pool.values()) - excluded_by_labels, rules
        counts = await pool_counts(session, rules)
        assert counts.allowed == len(kept)
        for i, rule in enumerate(rules):
            excluded = sum(1 for results in labels.values() if results[i].excludes)
            assert counts.ruled_out_by_rule[rule.kind] == excluded


async def test_eligibility_breakdown_is_reported_when_a_country_is_given(
    session: AsyncSession, pool: dict[str, uuid.UUID]
) -> None:
    counts = await pool_counts(session, [WorkEligibility(country="IN")])
    # Two worldwide jobs and the India one are eligible, the US one is not, one is unknown.
    assert counts.eligibility == {"eligible": 3, "unknown": 1, "ineligible": 1}
    assert counts.flagged_by_rule == {"work_eligibility": 1}


async def test_startup_backed_passes_known_backing_and_keeps_unknown_unless_strict(
    session: AsyncSession,
) -> None:
    from app.retrieval.rules import StartupBacked

    yc = await add_company(session, "YC Co")
    yc.yc_batch = "Winter 2024"
    vc = await add_company(session, "VC Co")
    vc.investors = ["elevation"]
    plain = await add_company(session, "Plain Co")
    jobs = {
        "yc": await add_job(session, yc, "Engineer"),
        "vc": await add_job(session, vc, "Engineer"),
        "plain": await add_job(session, plain, "Engineer"),
    }
    await session.commit()
    ids = {name: job.id for name, job in jobs.items()}

    rule = StartupBacked()
    assert names(set(await allowed_ids(session, [rule])), ids) == {"yc", "vc", "plain"}
    labels = await outcomes(session, [rule], list(ids.values()))
    assert {n: labels[i][0].outcome for n, i in ids.items()} == {
        "yc": "pass",
        "vc": "pass",
        "plain": "unknown",
    }
    strict = StartupBacked(strict=True)
    assert names(set(await allowed_ids(session, [strict])), ids) == {"yc", "vc"}
    only_yc = StartupBacked(backers=["yc"], strict=True)
    assert names(set(await allowed_ids(session, [only_yc])), ids) == {"yc"}
    assert only_yc.describe() == "Backed by Y Combinator"
