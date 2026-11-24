"""Engagement and poster tags: deterministic, no LLM. Rules live in data/tags.yaml.

engagement_type: the source's structured employment type (already in employment_type:
the source's field first, then the title), overridden by freelance_gig when the title is
gig work, or when the job is contract/part-time and the text describes per-hour or
per-task pay.

poster_type: staffing_agency when the company name marks a recruiter/consultancy/
staffing firm (minus listed exceptions) or the description says it hires for a client;
otherwise employer.
"""

import re
from dataclasses import dataclass
from functools import cache
from pathlib import Path

import yaml

_RULES = Path(__file__).resolve().parent / "data" / "tags.yaml"
ENGAGEMENT_TYPES = ("full_time", "part_time", "contract", "internship", "freelance_gig")
POSTER_TYPES = ("employer", "staffing_agency")
# The description is long; the decisive phrases are near the top (who is hiring, pay).
_TEXT_CHARS = 6000


@dataclass(frozen=True)
class _Rules:
    gig_title: re.Pattern[str]
    gig_text: re.Pattern[str]
    agency_name: re.Pattern[str]
    agency_name_exceptions: re.Pattern[str]
    agency_text: re.Pattern[str]
    agency_text_negations: re.Pattern[str]


def _any(patterns: list[str]) -> re.Pattern[str]:
    return re.compile("|".join(f"(?:{p})" for p in patterns), re.I)


@cache
def rules() -> _Rules:
    raw = yaml.safe_load(_RULES.read_text(encoding="utf-8"))
    e, p = raw["engagement"], raw["poster"]
    return _Rules(
        gig_title=_any(e["gig_title"]),
        gig_text=_any(e["gig_text"]),
        agency_name=_any(p["agency_name"]),
        agency_name_exceptions=_any(p["agency_name_exceptions"]),
        agency_text=_any(p["agency_text"]),
        agency_text_negations=_any(p["agency_text_negations"]),
    )


def engagement_type(employment_type: str, title: str, description: str) -> str:
    r = rules()
    base = employment_type if employment_type in ENGAGEMENT_TYPES else "full_time"
    if base == "internship":
        return base
    if r.gig_title.search(title):
        return "freelance_gig"
    if base in ("contract", "part_time") and r.gig_text.search(description[:_TEXT_CHARS]):
        return "freelance_gig"
    return base


def poster_type(company_name: str, description: str) -> str:
    r = rules()
    name = company_name.strip()
    if r.agency_name.search(name) and not r.agency_name_exceptions.search(name):
        return "staffing_agency"
    text = _without_negated_sentences(description[:_TEXT_CHARS], r.agency_text_negations)
    if r.agency_text.search(text):
        return "staffing_agency"
    return "employer"


def _without_negated_sentences(text: str, negations: re.Pattern[str]) -> str:
    """Removes each sentence (up to '.' or a line break) that contains a negation."""
    out: list[str] = []
    position = 0
    for match in negations.finditer(text):
        start = max(text.rfind(".", 0, match.start()), text.rfind("\n", 0, match.start())) + 1
        if start < position:
            continue  # inside a sentence already removed
        ends = [i for i in (text.find(".", match.end()), text.find("\n", match.end())) if i >= 0]
        out.append(text[position:start])
        position = min(ends) + 1 if ends else len(text)
    out.append(text[position:])
    return " ".join(out)
