"""Request and response shapes for search and match explanations."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.retrieval.rules import DealbreakerRule
from app.retrieval.scoring import Components, Explanation, SearchProfile


class SearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str | None = Field(
        default=None,
        max_length=300,
        description="What to look for. Optional when the profile lists skills.",
    )
    profile: SearchProfile | None = None
    rules: list[DealbreakerRule] = Field(default_factory=list, max_length=20)
    limit: int = Field(default=10, ge=1, le=30)

    @model_validator(mode="after")
    def _something_to_search(self) -> "SearchRequest":
        if self.query is not None:
            self.query = " ".join(self.query.split()) or None
        if self.query is None and not (self.profile and self.profile.skills):
            raise ValueError("give a query, or a profile with skills")
        return self

    def query_text(self) -> str:
        """The text both retrievers and the reranker read."""
        if self.query:
            return self.query
        skills = self.profile.canonical_skills().values() if self.profile else []
        return " ".join(skills)


class Salary(BaseModel):
    min: float | None
    max: float | None
    currency: str | None
    interval: str | None
    min_usd: int | None = Field(description="Annual, converted with the dated FX table")
    max_usd: int | None


class JobSummary(BaseModel):
    id: uuid.UUID
    title: str
    company: str
    location: str
    remote_policy: str
    seniority: str
    employment_type: str
    salary: Salary
    skills: list[str]
    source: str
    source_url: str
    posted_at: datetime | None
    status: str


class StageRanks(BaseModel):
    bm25: int | None = Field(description="1-based rank in the BM25 list; null if not in it")
    vector: int | None
    fused: int


class Scores(BaseModel):
    final: float
    rerank_logit: float | None = Field(
        description="null below the reranked head (see `reranked`), or with no rerank"
    )
    rrf: float
    components: Components
    ranks: StageRanks


class SearchResult(BaseModel):
    rank: int
    job: JobSummary
    scores: Scores
    explanation: Explanation


class RuleBreach(BaseModel):
    kind: str
    rule: str
    outcome: Literal["violates", "unknown"]
    reason: str | None = Field(description="For `unknown` under a strict rule: what is missing")


class RuledOut(BaseModel):
    job: JobSummary
    rules: list[RuleBreach] = Field(min_length=1)


class PoolSummary(BaseModel):
    pool: int = Field(description="Current, non-duplicate postings")
    allowed: int = Field(description="Postings left after the dealbreakers")
    ruled_out_by_rule: dict[str, int]
    flagged_by_rule: dict[str, int]
    eligibility: dict[str, int] | None


class SearchResponse(BaseModel):
    query: str
    results: list[SearchResult]
    ruled_out: list[RuledOut] = Field(
        description="Postings that matched the query but a dealbreaker excluded, best first"
    )
    pool: PoolSummary
    bm25_version: str | None
    rerank_profile: str = Field(description="`interactive` for POST /search")
    reranked: int = Field(description="How many fused candidates the cross-encoder scored")
    degraded: list[str] = Field(description="Stages that were skipped, e.g. bm25_unavailable")
    timings_ms: dict[str, float]
    cached: bool = False


class ExplanationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: uuid.UUID
    profile: SearchProfile | None = None
    rules: list[DealbreakerRule] = Field(default_factory=list, max_length=20)


class ExplanationSentence(BaseModel):
    job_id: uuid.UUID
    explanation: Explanation
    sentence: str | None
    status: Literal["ok", "dropped", "unavailable"] = Field(
        description="dropped: the sentence named a skill not in the explanation"
    )
    detail: str | None = None
    quota_remaining: int
