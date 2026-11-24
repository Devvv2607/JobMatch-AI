"""The filter stage: which jobs a search may return, and why the others were ruled out.

Every query here is built from the same per-rule outcome expressions (rules.py), so the
allowed set, the per-job labels and the counts always agree.
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import cast

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Company, Job
from app.retrieval.rules import Outcome, Rule, WorkEligibility, allowed, base_pool, needs_company


@dataclass(frozen=True)
class RuleResult:
    rule: Rule
    outcome: Outcome

    @property
    def excludes(self) -> bool:
        return self.outcome == "violates" or (self.outcome == "unknown" and self.rule.strict)

    @property
    def flags(self) -> bool:
        return self.outcome == "unknown" and not self.rule.strict


def _from_jobs[*Ts](statement: Select[*Ts], rules: Sequence[Rule]) -> Select[*Ts]:
    if needs_company(rules):
        return statement.join(Company, Company.id == Job.company_id)
    return statement


async def allowed_ids(session: AsyncSession, rules: Sequence[Rule]) -> list[uuid.UUID]:
    statement = _from_jobs(select(Job.id), rules).where(allowed(rules))
    return list((await session.scalars(statement)).all())


async def outcomes(
    session: AsyncSession, rules: Sequence[Rule], ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, list[RuleResult]]:
    """Each rule's outcome for each of `ids` (jobs outside the pool are omitted)."""
    if not ids:
        return {}
    columns = [rule.outcome().label(f"r{i}") for i, rule in enumerate(rules)]
    statement = _from_jobs(select(Job.id, *columns), rules).where(
        base_pool(), Job.id.in_(list(ids))
    )
    result: dict[uuid.UUID, list[RuleResult]] = {}
    for row in (await session.execute(statement)).all():
        result[row[0]] = [
            RuleResult(rule, cast(Outcome, row[i + 1])) for i, rule in enumerate(rules)
        ]
    return result


@dataclass(frozen=True)
class PoolCounts:
    pool: int
    allowed: int
    ruled_out_by_rule: dict[str, int]  # rule kind -> jobs it excludes (a job can count twice)
    flagged_by_rule: dict[str, int]  # rule kind -> jobs kept but flagged
    eligibility: dict[str, int] | None  # eligible / unknown / ineligible, if a country is known


async def pool_counts(session: AsyncSession, rules: Sequence[Rule]) -> PoolCounts:
    columns = [func.count().label("pool"), func.count().filter(allowed(rules)).label("allowed")]
    for i, rule in enumerate(rules):
        excluded = ("violates", "unknown") if rule.strict else ("violates",)
        columns.append(func.count().filter(rule.outcome().in_(excluded)).label(f"x{i}"))
        flagged = rule.outcome() == "unknown" if not rule.strict else None
        if flagged is not None:
            columns.append(func.count().filter(flagged).label(f"f{i}"))
    eligibility = next((r for r in rules if isinstance(r, WorkEligibility)), None)
    if eligibility is not None:
        labels = (("eligible", "pass"), ("unknown", "unknown"), ("ineligible", "violates"))
        for name, value in labels:
            columns.append(func.count().filter(eligibility.outcome() == value).label(f"e_{name}"))
    statement = _from_jobs(select(*columns), rules).where(base_pool())
    row = (await session.execute(statement)).mappings().one()

    ruled_out: dict[str, int] = {}
    flagged_counts: dict[str, int] = {}
    for i, rule in enumerate(rules):
        kind = rule.kind
        ruled_out[kind] = ruled_out.get(kind, 0) + row[f"x{i}"]
        if f"f{i}" in row:
            flagged_counts[kind] = flagged_counts.get(kind, 0) + row[f"f{i}"]
    return PoolCounts(
        pool=row["pool"],
        allowed=row["allowed"],
        ruled_out_by_rule=ruled_out,
        flagged_by_rule=flagged_counts,
        eligibility=(
            {name: row[f"e_{name}"] for name in ("eligible", "unknown", "ineligible")}
            if eligibility is not None
            else None
        ),
    )
