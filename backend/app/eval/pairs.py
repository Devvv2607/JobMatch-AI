"""The unit of judgement: one (profile, job) pair, with everything the judge and the
labeller see about the job frozen into the record, so labels never depend on the live
database. Pooling (after the snapshot) writes these; the demo sample writes a few.

Files in a label set folder (eval/labels/<set>/):
- pairs.jsonl   one EvalPair per line
- judge.jsonl   one JudgeRecord per line (app/eval/judge.py)
- plan.json     the labelling order, fixed at the first start (app/eval/labels.py)
- human.jsonl   the labelling event log, appended and fsynced per key press
"""

import json
import os
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class JobCard(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: str
    title: str
    company: str
    source: str
    location: str
    locations: list[str] = Field(default_factory=list)
    eligibility: str  # in words: "worldwide", "IN, US", "unknown"
    workplace: str
    employment: str  # engagement_type
    poster: str  # poster_type
    salary: str | None = None
    posted_at: str | None = None
    url: str | None = None
    description: str  # boilerplate-stripped, truncated


class EvalPair(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pair_id: str
    profile_id: str
    job: JobCard
    variants: dict[str, int] = Field(default_factory=dict)  # variant -> rank it surfaced at
    strata: dict[str, str] = Field(default_factory=dict)  # source, employment, poster, ...


class JudgeRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pair_id: str
    label: int = Field(ge=0, le=3)
    reason: str
    # None for a rater that gives no confidence (an agent's grades, owner 2026-11-26).
    confidence: Literal["low", "medium", "high"] | None
    provider: str
    model: str
    prompt: str  # name and version, e.g. eval_judge/v1
    cached: bool = False
    prompt_tokens: int | None = None  # as the provider reported them (None: not recorded)
    completion_tokens: int | None = None
    # "llm" for every machine grade; set explicitly on imported agent grades.
    label_source: Literal["llm"] | None = None


def pair_id(profile_id: str, job_id: str) -> str:
    return f"{profile_id}:{job_id}"


def read_jsonl(path: Path) -> Iterator[dict[str, object]]:
    if not path.exists():
        return
    with path.open(encoding="utf-8") as f:
        for line in f:
            if line.strip():
                yield json.loads(line)


def append_jsonl(path: Path, record: BaseModel | dict[str, object]) -> None:
    """Appends one line and forces it to disk before returning (autosave)."""
    data = record.model_dump(mode="json") if isinstance(record, BaseModel) else record
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(data, ensure_ascii=False) + "\n")
        f.flush()
        os.fsync(f.fileno())


def write_jsonl(path: Path, records: Iterable[BaseModel]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record.model_dump(mode="json"), ensure_ascii=False) + "\n")


def load_pairs(path: Path) -> list[EvalPair]:
    pairs = [EvalPair.model_validate(r) for r in read_jsonl(path)]
    ids = [p.pair_id for p in pairs]
    if len(ids) != len(set(ids)):
        raise ValueError(f"{path}: duplicate pair ids")
    return pairs


def load_judge(path: Path) -> dict[str, JudgeRecord]:
    """The latest judge record per pair (a re-judged pair's later line wins)."""
    return {r.pair_id: r for r in (JudgeRecord.model_validate(x) for x in read_jsonl(path))}
