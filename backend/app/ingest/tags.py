"""Engagement and poster tags: deterministic, no LLM. Rules live in data/tags.yaml.

engagement_type: the source's structured employment type (already in employment_type:
the source's field first, then the title), overridden by freelance_gig when
- the title is gig work (AI trainer, rater, talent hub, commission-based...), or the
  text says commission-only pay;
- the poster is an AI-data vendor (micro1, Mercor, ...) and the job is contract or
  part-time, or its title/text gives hourly pay or AI-training work;
- the job is contract/part-time and the text describes AI-training work, or per-hour /
  per-task pay (unless a staffing agency posted it: its hourly contracts are contracts).

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
    ai_work_text: re.Pattern[str]
    commission_text: re.Pattern[str]
    ai_vendors: re.Pattern[str]
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
        ai_work_text=_any(e["ai_work_text"]),
        commission_text=_any(e["commission_text"]),
        ai_vendors=_any(e["ai_vendors"]),
        agency_name=_any(p["agency_name"]),
        agency_name_exceptions=_any(p["agency_name_exceptions"]),
        agency_text=_any(p["agency_text"]),
        agency_text_negations=_any(p["agency_text_negations"]),
    )


def engagement_type(employment_type: str, title: str, description: str, company: str) -> str:
    return explain_engagement(employment_type, title, description, company)[0]


def explain_engagement(
    employment_type: str, title: str, description: str, company: str
) -> tuple[str, str]:
    """(engagement_type, the rule that decided it), for review sheets."""
    r = rules()
    base = employment_type if employment_type in ENGAGEMENT_TYPES else "full_time"
    gig = "freelance_gig"
    if base == "internship":
        return base, "employment_type internship"
    text = description[:_TEXT_CHARS]
    if m := r.gig_title.search(title):
        return gig, f"title: '{m.group(0)}'"
    if m := r.commission_text.search(text):
        return gig, f"text: '{m.group(0)}'"
    if r.ai_vendors.search(company.strip()):
        if base in ("contract", "part_time"):
            return gig, f"AI-data vendor + {base}"
        if m := r.gig_text.search(title) or r.ai_work_text.search(f"{title}\n{text}"):
            return gig, f"AI-data vendor + '{m.group(0)}'"
        return base, f"employment_type {base} (AI-data vendor, no gig signal)"
    if base in ("contract", "part_time"):
        if m := r.ai_work_text.search(text):
            return gig, f"{base} + AI work: '{m.group(0)}'"
        # A staffing agency's hourly contract (e.g. a 6-9 month subcontract) is a contract.
        if m := r.gig_text.search(f"{title}\n{text}"):
            if poster_type(company, description) != "staffing_agency":
                return gig, f"{base} + pay: '{m.group(0)}'"
            return base, f"employment_type {base} (agency; '{m.group(0)}' ignored)"
    return base, f"employment_type {base}"


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
