"""Fusion, the personalised re-score and the explanation object. Pure functions: no I/O.

Re-score: every component is in [0, 1]; the final score is the weighted mean of the
components available for that job (weights in config). A component is unavailable when
the request or the posting lacks what it needs (no profile skills, no skills listed in
the posting...), and is then left out of the mean rather than counted as 0 or 1.

Explanation: built only from structured fields (taxonomy skills, seniority, workplace,
the rule outcomes), never from the description text, so every statement in it can be
traced to a column. The optional LLM sentence is given this object and nothing else.
"""

import math
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.ingest.countries import country_code
from app.ingest.skills import canonical_skill
from app.retrieval.rules import Seniority, Workplace

# Years of experience each level usually asks for (inclusive band). Coarse by design:
# it only feeds a small re-score weight and the "experience" line of the explanation.
EXPECTED_YEARS: dict[str, tuple[int, int]] = {
    "intern": (0, 1),
    "junior": (0, 2),
    "mid": (2, 5),
    "senior": (5, 10),
    "lead": (6, 15),
    "staff": (8, 20),
    "principal": (10, 25),
    "manager": (5, 15),
    "director": (10, 30),
    "executive": (15, 40),
}
# Score lost per year outside the band.
_EXPERIENCE_DECAY = 0.25


class Preferences(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workplace: list[Workplace] = Field(default_factory=list, max_length=3)
    countries: list[str] = Field(
        default_factory=list, max_length=20, description="ISO codes the candidate would work in"
    )
    seniority: list[Seniority] = Field(default_factory=list, max_length=10)

    @field_validator("countries")
    @classmethod
    def _iso(cls, values: list[str]) -> list[str]:
        codes = []
        for value in values:
            code = country_code(value)
            if code is None:
                raise ValueError(f"unknown country: {value}")
            codes.append(code)
        return codes


class SearchProfile(BaseModel):
    """What the candidate brings. Until resume parsing exists (Phase 5) it is sent with
    the request; then it will be read from the stored profile."""

    model_config = ConfigDict(extra="forbid")

    skills: list[str] = Field(default_factory=list, max_length=100)
    years_experience: float | None = Field(default=None, ge=0, le=60)
    preferences: Preferences = Field(default_factory=Preferences)

    @field_validator("skills")
    @classmethod
    def _bounded(cls, values: list[str]) -> list[str]:
        cleaned = [" ".join(v.split()) for v in values]
        if any(not v or len(v) > 64 for v in cleaned):
            raise ValueError("each skill must be 1-64 characters")
        return cleaned

    def canonical_skills(self) -> dict[str, str]:
        """Lower-cased canonical name -> the name to show. Skills outside the taxonomy are
        kept as typed, so they can still match a posting's skill of the same name."""
        out: dict[str, str] = {}
        for raw in self.skills:
            name = canonical_skill(raw) or raw
            out.setdefault(name.lower(), name)
        return out

    def is_empty(self) -> bool:
        p = self.preferences
        return (
            not self.skills
            and self.years_experience is None
            and not (p.workplace or p.countries or p.seniority)
        )


def rrf(rankings: Sequence[Sequence[uuid.UUID]], k: int) -> list[tuple[uuid.UUID, float]]:
    """Reciprocal rank fusion: sum of 1 / (k + rank) over the lists a job appears in
    (rank starts at 1). Ties keep first-seen order, so the result is deterministic."""
    scores: dict[uuid.UUID, float] = {}
    for ranking in rankings:
        for rank, job_id in enumerate(ranking, start=1):
            scores[job_id] = scores.get(job_id, 0.0) + 1.0 / (k + rank)
    return sorted(scores.items(), key=lambda item: -item[1])


def sigmoid(logit: float) -> float:
    if logit >= 0:
        return 1.0 / (1.0 + math.exp(-logit))
    e = math.exp(logit)
    return e / (1.0 + e)


@dataclass(frozen=True)
class JobFacts:
    """The structured fields of a posting the score and explanation read."""

    skills: list[str]
    seniority: str
    remote_policy: str
    work_countries: list[str]
    eligibility_scope: str


class SkillMatch(BaseModel):
    matched: list[str] = Field(description="Posting skills the candidate listed")
    missing: list[str] = Field(description="Posting skills the candidate did not list")
    coverage: float | None = Field(
        description="matched / posting skills; null when the posting lists none or no profile"
    )


class ExperienceFit(BaseModel):
    seniority: str
    expected_years: tuple[int, int] | None
    candidate_years: float | None
    fit: Literal["within", "below", "above", "unknown"]


class PreferenceMatch(BaseModel):
    name: Literal["workplace", "countries", "seniority"]
    wanted: list[str]
    job: list[str]
    match: bool | None = Field(description="null when the posting does not say")


class RuleFlag(BaseModel):
    kind: str
    rule: str = Field(description="What the dealbreaker asks for")
    reason: str = Field(description="Why the posting could not be checked against it")


class Components(BaseModel):
    rerank: float = Field(description="Cross-encoder relevance, sigmoid of the logit")
    skills: float | None
    experience: float | None
    preferences: float | None


class Explanation(BaseModel):
    skills: SkillMatch
    experience: ExperienceFit
    preferences: list[PreferenceMatch]
    flags: list[RuleFlag] = Field(
        description="Dealbreakers the posting could not be checked against; it was kept"
    )


def skill_match(profile: SearchProfile | None, job_skills: list[str]) -> SkillMatch:
    if profile is None or not profile.skills:
        return SkillMatch(matched=[], missing=list(job_skills), coverage=None)
    have = profile.canonical_skills()
    matched = [s for s in job_skills if s.lower() in have]
    missing = [s for s in job_skills if s.lower() not in have]
    coverage = len(matched) / len(job_skills) if job_skills else None
    return SkillMatch(matched=matched, missing=missing, coverage=coverage)


def experience_fit(
    profile: SearchProfile | None, seniority: str
) -> tuple[ExperienceFit, float | None]:
    band = EXPECTED_YEARS.get(seniority)
    years = profile.years_experience if profile else None
    if band is None or years is None:
        return ExperienceFit(
            seniority=seniority, expected_years=band, candidate_years=years, fit="unknown"
        ), None
    low, high = band
    if years < low:
        fit, gap = "below", low - years
    elif years > high:
        fit, gap = "above", years - high
    else:
        fit, gap = "within", 0.0
    score = max(0.0, 1.0 - _EXPERIENCE_DECAY * gap)
    return ExperienceFit(
        seniority=seniority, expected_years=band, candidate_years=years, fit=fit
    ), score


def preference_matches(profile: SearchProfile | None, job: JobFacts) -> list[PreferenceMatch]:
    if profile is None:
        return []
    prefs = profile.preferences
    out: list[PreferenceMatch] = []
    if prefs.workplace:
        known = job.remote_policy != "unknown"
        out.append(
            PreferenceMatch(
                name="workplace",
                wanted=list(prefs.workplace),
                job=[job.remote_policy],
                match=(job.remote_policy in prefs.workplace) if known else None,
            )
        )
    if prefs.countries:
        if job.eligibility_scope == "worldwide":
            match: bool | None = True
        elif job.eligibility_scope == "listed":
            match = bool(set(prefs.countries) & set(job.work_countries))
        else:
            match = None
        out.append(
            PreferenceMatch(
                name="countries",
                wanted=list(prefs.countries),
                job=["worldwide"] if job.eligibility_scope == "worldwide" else job.work_countries,
                match=match,
            )
        )
    if prefs.seniority:
        out.append(
            PreferenceMatch(
                name="seniority",
                wanted=list(prefs.seniority),
                job=[job.seniority],
                match=job.seniority in prefs.seniority,
            )
        )
    return out


def preference_score(matches: list[PreferenceMatch]) -> float | None:
    """Mean over stated preferences: 1 match, 0 mismatch, 0.5 when the posting is silent."""
    if not matches:
        return None
    values = [0.5 if m.match is None else float(m.match) for m in matches]
    return sum(values) / len(values)


@dataclass(frozen=True)
class Weights:
    rerank: float
    skills: float
    experience: float
    preferences: float


def final_score(components: Components, weights: Weights) -> float:
    parts = [(components.rerank, weights.rerank)]
    for value, weight in (
        (components.skills, weights.skills),
        (components.experience, weights.experience),
        (components.preferences, weights.preferences),
    ):
        if value is not None:
            parts.append((value, weight))
    total = sum(w for _, w in parts)
    if total == 0:
        return components.rerank
    return sum(v * w for v, w in parts) / total


def explain(
    profile: SearchProfile | None, job: JobFacts, rerank_logit: float, flags: list[RuleFlag]
) -> tuple[Explanation, Components]:
    skills = skill_match(profile, job.skills)
    experience, experience_score = experience_fit(profile, job.seniority)
    preferences = preference_matches(profile, job)
    components = Components(
        rerank=sigmoid(rerank_logit),
        skills=skills.coverage,
        experience=experience_score,
        preferences=preference_score(preferences),
    )
    return (
        Explanation(skills=skills, experience=experience, preferences=preferences, flags=flags),
        components,
    )
