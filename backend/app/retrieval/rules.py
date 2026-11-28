"""Dealbreakers: typed rules that compile to SQL.

Each rule defines two SQL conditions over a job (and its company):
  unknown -- the rule cannot be evaluated (salary not listed, workplace not stated...)
  passes  -- the job satisfies the rule (only consulted when not unknown)

Both are folded into ONE expression per rule, its *outcome*:

    CASE WHEN unknown THEN 'unknown' WHEN passes THEN 'pass' ELSE 'violates' END

and the filter is built from that same expression (`outcome IN allowed outcomes`). The
"Ruled out" labels are read from the same expression too, so the list of excluded jobs
and the reason given for each can never disagree with what the filter removed.

Strictness: `strict=False` (the default) keeps a job the rule cannot evaluate and flags
it; `strict=True` rules it out. A job that clearly violates a rule is always ruled out.

Adding a rule type: subclass `Rule`, give it a unique `kind` literal, implement
`unknown`/`passes`/`describe`, and add it to `DealbreakerRule` below. Nothing else changes.
"""

from collections.abc import Sequence
from typing import Annotated, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import ColumnElement, and_, case, false, func, literal, not_, or_
from sqlalchemy.dialects.postgresql import array

from app.ingest.companies import company_slug
from app.ingest.countries import country_code
from app.models import Company, Job

Outcome = Literal["pass", "unknown", "violates"]

Workplace = Literal["remote", "hybrid", "onsite"]
Seniority = Literal[
    "intern",
    "junior",
    "mid",
    "senior",
    "lead",
    "staff",
    "principal",
    "manager",
    "director",
    "executive",
]
EmploymentType = Literal["full_time", "part_time", "contract", "internship"]


class Rule(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: str
    strict: bool = Field(
        default=False,
        description="Rule out jobs this rule cannot evaluate, instead of keeping and flagging.",
    )
    # Whether the rule reads columns of the job's company (the query then joins it).
    needs_company: ClassVar[bool] = False

    def unknown(self) -> ColumnElement[bool]:
        """True when the rule cannot be evaluated for a job. Never NULL."""
        return false()

    def passes(self) -> ColumnElement[bool]:
        """True when the job satisfies the rule. Only consulted when not unknown."""
        raise NotImplementedError

    def describe(self) -> str:
        """What the rule asks for, in words, for the ruled-out list and flags."""
        raise NotImplementedError

    def unknown_reason(self) -> str:
        return "Not stated in the posting"

    def outcome(self) -> ColumnElement[str]:
        return case(
            (self.unknown(), literal("unknown")),
            (func.coalesce(self.passes(), false()), literal("pass")),
            else_=literal("violates"),
        )

    def allows(self) -> ColumnElement[bool]:
        allowed = ("pass",) if self.strict else ("pass", "unknown")
        return self.outcome().in_(allowed)


class WorkEligibility(Rule):
    """The candidate must be legally able to do the job from their country. Reads the
    countries of the job and of every duplicate merged into it (all_work_countries), so
    a merged posting is not lost to candidates in a variant's country."""

    kind: Literal["work_eligibility"] = "work_eligibility"
    country: str = Field(description="ISO 3166-1 alpha-2 code, e.g. IN")

    @field_validator("country")
    @classmethod
    def _iso(cls, value: str) -> str:
        code = country_code(value)
        if code is None:
            raise ValueError("unknown country")
        return code

    def unknown(self) -> ColumnElement[bool]:
        return and_(
            Job.eligibility_scope == "unknown", func.cardinality(Job.all_work_countries) == 0
        )

    def passes(self) -> ColumnElement[bool]:
        return or_(
            Job.eligibility_scope == "worldwide",
            Job.all_work_countries.contains([self.country]),
        )

    def describe(self) -> str:
        return f"Open to candidates in {self.country}"

    def unknown_reason(self) -> str:
        return "The posting does not say where the job can be done from"


class LocationRule(Rule):
    """The posting names one of these places (city, state or country, as written). Matches
    the locations of the job and of every duplicate merged into it, so a role posted in
    several cities is found from any of them. A job with no location is unknown."""

    kind: Literal["location"] = "location"
    places: list[str] = Field(min_length=1, max_length=20)

    @field_validator("places")
    @classmethod
    def _clean(cls, value: list[str]) -> list[str]:
        cleaned = [" ".join(p.split()) for p in value if p.strip()]
        if not cleaned:
            raise ValueError("at least one place")
        return cleaned

    def unknown(self) -> ColumnElement[bool]:
        return func.cardinality(Job.all_locations) == 0

    def passes(self) -> ColumnElement[bool]:
        # One line per location: a place (whitespace-normalised, so no newline) can only
        # match within a single location.
        joined = func.array_to_string(Job.all_locations, "\n")
        return or_(*(joined.ilike(f"%{_escape_like(p)}%", escape="\\") for p in self.places))

    def describe(self) -> str:
        return f"Located in: {', '.join(self.places)}"

    def unknown_reason(self) -> str:
        return "The posting gives no location"


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


class WorkplaceRule(Rule):
    kind: Literal["workplace"] = "workplace"
    allowed: list[Workplace] = Field(min_length=1)

    def unknown(self) -> ColumnElement[bool]:
        return Job.remote_policy == "unknown"

    def passes(self) -> ColumnElement[bool]:
        return Job.remote_policy.in_(self.allowed)

    def describe(self) -> str:
        return f"Workplace: {' or '.join(self.allowed)}"

    def unknown_reason(self) -> str:
        return "The posting does not say whether it is remote, hybrid or on-site"


class MinSalary(Rule):
    """Annual salary in USD (converted with the dated FX table). The top of the posted
    range is compared, so a range that reaches the minimum passes."""

    kind: Literal["min_salary_usd"] = "min_salary_usd"
    amount: int = Field(gt=0)

    def unknown(self) -> ColumnElement[bool]:
        return and_(Job.salary_min_usd.is_(None), Job.salary_max_usd.is_(None))

    def passes(self) -> ColumnElement[bool]:
        return func.coalesce(Job.salary_max_usd, Job.salary_min_usd) >= self.amount

    def describe(self) -> str:
        return f"Salary at least USD {self.amount:,} a year"

    def unknown_reason(self) -> str:
        return "Salary not listed"


class SeniorityRule(Rule):
    kind: Literal["seniority"] = "seniority"
    allowed: list[Seniority] = Field(min_length=1)

    def passes(self) -> ColumnElement[bool]:
        return Job.seniority.in_(self.allowed)

    def describe(self) -> str:
        return f"Level: {', '.join(self.allowed)}"


class EmploymentTypeRule(Rule):
    kind: Literal["employment_type"] = "employment_type"
    allowed: list[EmploymentType] = Field(min_length=1)

    def passes(self) -> ColumnElement[bool]:
        return Job.employment_type.in_(self.allowed)

    def describe(self) -> str:
        return f"Employment: {', '.join(self.allowed)}"


class ExcludeFreelanceGigs(Rule):
    """Excludes per-task / per-hour gig work (AI training, rating, annotation...), tagged
    engagement_type = freelance_gig by app/ingest/tags.py. Off unless the user adds it."""

    kind: Literal["exclude_freelance_gigs"] = "exclude_freelance_gigs"

    def passes(self) -> ColumnElement[bool]:
        return Job.engagement_type != "freelance_gig"

    def describe(self) -> str:
        return "No freelance or gig work"


class ExcludeStaffingAgencies(Rule):
    """Excludes postings by recruiters and staffing firms hiring for a client, tagged
    poster_type = staffing_agency by app/ingest/tags.py. Off unless the user adds it."""

    kind: Literal["exclude_staffing_agencies"] = "exclude_staffing_agencies"

    def passes(self) -> ColumnElement[bool]:
        return Job.poster_type != "staffing_agency"

    def describe(self) -> str:
        return "No staffing agencies"


class ExcludeIndustries(Rule):
    """Industry tags come from companies.yaml; companies without tags are unknown."""

    kind: Literal["exclude_industries"] = "exclude_industries"
    industries: list[str] = Field(min_length=1, max_length=50)
    needs_company: ClassVar[bool] = True

    def unknown(self) -> ColumnElement[bool]:
        return func.cardinality(Company.industries) == 0

    def passes(self) -> ColumnElement[bool]:
        overlaps: ColumnElement[bool] = Company.industries.overlap(
            array([i.lower() for i in self.industries])
        )
        return not_(overlaps)

    def describe(self) -> str:
        return f"Not in: {', '.join(self.industries)}"

    def unknown_reason(self) -> str:
        return "Company industry unknown"


class ExcludeCompanies(Rule):
    kind: Literal["exclude_companies"] = "exclude_companies"
    companies: list[str] = Field(min_length=1, max_length=200)
    needs_company: ClassVar[bool] = True

    def passes(self) -> ColumnElement[bool]:
        return Company.slug.not_in([company_slug(c) for c in self.companies])

    def describe(self) -> str:
        return f"Not at: {', '.join(self.companies)}"


class StartupBacked(Rule):
    """The company is backed by Y Combinator (a YC batch, from the yc-oss dataset) or by a
    VC firm (investors from a portfolio page we may read). A company with neither recorded
    is unknown, not "not backed": the curated companies.yaml records no backing at all.
    So the rule keeps and flags unknown companies by default, and only `strict` limits
    results to companies known to be backed."""

    kind: Literal["startup_backed"] = "startup_backed"
    backers: list[Literal["yc", "vc"]] = Field(default=["yc", "vc"], min_length=1)
    needs_company: ClassVar[bool] = True

    def _known(self) -> list[ColumnElement[bool]]:
        known: list[ColumnElement[bool]] = []
        if "yc" in self.backers:
            known.append(Company.yc_batch.is_not(None))
        if "vc" in self.backers:
            known.append(func.cardinality(Company.investors) > 0)
        return known

    def unknown(self) -> ColumnElement[bool]:
        return not_(or_(*self._known()))

    def passes(self) -> ColumnElement[bool]:
        return or_(*self._known())

    def describe(self) -> str:
        names = {"yc": "Y Combinator", "vc": "a VC firm"}
        return "Backed by " + " or ".join(names[b] for b in self.backers)

    def unknown_reason(self) -> str:
        return "Not known to be startup-backed"


class PostedWithinDays(Rule):
    """Posted in the last N days, by the posting's own date. A posting without a date
    is unknown (every source so far gives one: 0 of 11,531 on 2026-11-24)."""

    kind: Literal["posted_within_days"] = "posted_within_days"
    days: int = Field(ge=1, le=365)

    def unknown(self) -> ColumnElement[bool]:
        return Job.posted_at.is_(None)

    def passes(self) -> ColumnElement[bool]:
        return Job.posted_at >= func.now() - func.make_interval(0, 0, 0, self.days)

    def describe(self) -> str:
        return f"Posted in the last {self.days} days"

    def unknown_reason(self) -> str:
        return "Posting date not given"


DealbreakerRule = Annotated[
    WorkEligibility
    | LocationRule
    | WorkplaceRule
    | MinSalary
    | SeniorityRule
    | EmploymentTypeRule
    | ExcludeIndustries
    | ExcludeCompanies
    | PostedWithinDays
    | StartupBacked
    | ExcludeFreelanceGigs
    | ExcludeStaffingAgencies,
    Field(discriminator="kind"),
]


def base_pool() -> ColumnElement[bool]:
    """Every search starts from the same pool: current, non-duplicate postings."""
    return and_(Job.status != "expired", Job.duplicate_of.is_(None))


def allowed(rules: Sequence[Rule]) -> ColumnElement[bool]:
    """The filter: the pool, minus every job some rule rules out."""
    return and_(base_pool(), *(rule.allows() for rule in rules))


def needs_company(rules: Sequence[Rule]) -> bool:
    return any(rule.needs_company for rule in rules)
