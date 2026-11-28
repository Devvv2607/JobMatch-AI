"""The fictional evaluation profiles (eval/profiles/*.yaml).

Each file is one candidate: a persona for the judge and the labeller, and the exact
search request (query, profile, dealbreaker rules) the retrieval variants are run with.
No real person's data: personas are written for the evaluation.
"""

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from app.eval import EVAL_DIR
from app.retrieval.rules import DealbreakerRule
from app.retrieval.schemas import SearchRequest
from app.retrieval.scoring import SearchProfile

Region = Literal["india", "us", "eu", "remote"]
ExperienceBand = Literal["fresher", "1-3", "3-6"]
Field_ = Literal["ml_ai", "data", "backend", "full_stack", "product_analyst"]

_RULES: TypeAdapter[list[DealbreakerRule]] = TypeAdapter(list[DealbreakerRule])


class JudgeNotes(BaseModel):
    model_config = ConfigDict(extra="forbid")

    a_3_looks_like: str = Field(min_length=10, max_length=400)
    rules_out: str = Field(min_length=10, max_length=400)


class EvalProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^p\d{2}$")
    region: Region
    lives_in: str
    experience_band: ExperienceBand
    field: Field_
    persona: str = Field(min_length=40, max_length=600)
    query: str = Field(min_length=3, max_length=120)
    profile: SearchProfile
    rules: list[DealbreakerRule] = Field(default_factory=list)
    judge_notes: JudgeNotes

    def search_request(self, *, with_query: bool = True, limit: int = 30) -> SearchRequest:
        """The request a variant is run with. `with_query=False` is the profile-only
        variant (the retrievers read the profile's skills)."""
        return SearchRequest(
            query=self.query if with_query else None,
            profile=self.profile,
            rules=list(self.rules),
            limit=limit,
        )

    def dealbreakers(self) -> list[str]:
        """The rules in words, as the search API describes them."""
        return [rule.describe() + (" (strict)" if rule.strict else "") for rule in self.rules]


def load_profiles(directory: Path | None = None) -> dict[str, EvalProfile]:
    """Every profile in the folder, by id. Raises on a duplicate id or an invalid file."""
    folder = directory or EVAL_DIR / "profiles"
    profiles: dict[str, EvalProfile] = {}
    for path in sorted(folder.glob("p*.yaml")):
        profile = EvalProfile.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
        if profile.id != path.stem:
            raise ValueError(f"{path.name}: id {profile.id} does not match the file name")
        if profile.id in profiles:
            raise ValueError(f"duplicate profile id {profile.id}")
        profiles[profile.id] = profile
    return profiles
