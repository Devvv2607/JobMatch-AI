"""Engagement, poster and evergreen tags: deterministic, no LLM. Rules live in
data/tags.yaml.

engagement_type: the source's structured employment type (already in employment_type:
the source's field first, then the title), overridden by freelance_gig when
- the title names gig work (freelance, gig, "train AI", commission-based), or the text
  says commission-only pay or a one-off fee ("$175 (One-Time Payment)");
- the title names AI-data work (AI trainer, rater, annotator...) AND there is AI-data
  context: the poster is an AI-data vendor, or the title or text speaks of training AI
  models or per-task / per-hour pay (owner review 2026-11-25: "AI Trainer" at a
  consulting firm that teaches AI is not gig work);
- the poster is an AI-data vendor (micro1, Mercor, Aptura...) and the job is contract
  or part-time, or its title/text gives hourly pay or AI-training work;
- the job is contract/part-time and the text describes AI-training work, or per-hour /
  per-task pay (unless a staffing agency posted it: its hourly contracts are contracts).

poster_type: staffing_agency when the company is a known agency, its name marks a
recruiter or staffing firm (minus listed exceptions), the description says it hires for
a client, or its name is ambiguous (Consultancy, Consulting, Solutions) and the text
has placement language ("talent network", "on-demand talent"); otherwise employer.

is_evergreen: a standing pipeline rather than an opening ("Talent Community",
"Expression of Interest", "seeking engineers to join our global talent network").
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
    ai_gig_title: re.Pattern[str]
    ai_title_context: re.Pattern[str]
    gig_text: re.Pattern[str]
    ai_work_text: re.Pattern[str]
    commission_text: re.Pattern[str]
    ai_vendors: re.Pattern[str]
    agency_name: re.Pattern[str]
    agency_name_ambiguous: re.Pattern[str]
    placement_text: re.Pattern[str]
    known_agencies: re.Pattern[str]
    agency_name_exceptions: re.Pattern[str]
    agency_text: re.Pattern[str]
    agency_text_negations: re.Pattern[str]
    evergreen_title: re.Pattern[str]
    evergreen_text: re.Pattern[str]


def _any(patterns: list[str]) -> re.Pattern[str]:
    return re.compile("|".join(f"(?:{p})" for p in patterns), re.I)


@cache
def rules() -> _Rules:
    raw = yaml.safe_load(_RULES.read_text(encoding="utf-8"))
    e, p, g = raw["engagement"], raw["poster"], raw["evergreen"]
    return _Rules(
        gig_title=_any(e["gig_title"]),
        ai_gig_title=_any(e["ai_gig_title"]),
        ai_title_context=_any(e["ai_title_context"]),
        gig_text=_any(e["gig_text"]),
        ai_work_text=_any(e["ai_work_text"]),
        commission_text=_any(e["commission_text"]),
        ai_vendors=_any(e["ai_vendors"]),
        agency_name=_any(p["agency_name"]),
        agency_name_ambiguous=_any(p["agency_name_ambiguous"]),
        placement_text=_any(p["placement_text"]),
        known_agencies=_any(p["known_agencies"]),
        agency_name_exceptions=_any(p["agency_name_exceptions"]),
        agency_text=_any(p["agency_text"]),
        agency_text_negations=_any(p["agency_text_negations"]),
        evergreen_title=_any(g["title"]),
        evergreen_text=_any(g["text"]),
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
    vendor = bool(r.ai_vendors.search(company.strip()))
    if m := r.ai_gig_title.search(title):
        if vendor:
            return gig, f"title: '{m.group(0)}' + AI-data vendor"
        if c := r.ai_title_context.search(f"{title}\n{text}"):
            return gig, f"title: '{m.group(0)}' + '{c.group(0)}'"
    if vendor:
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
    return explain_poster(company_name, description)[0]


def explain_poster(company_name: str, description: str) -> tuple[str, str]:
    """(poster_type, the rule that decided it), for review sheets."""
    r = rules()
    agency = "staffing_agency"
    name = company_name.strip()
    excepted = bool(r.agency_name_exceptions.search(name))
    if m := r.known_agencies.search(name):
        return agency, f"known agency: '{m.group(0)}'"
    if not excepted and (m := r.agency_name.search(name)):
        return agency, f"name: '{m.group(0)}'"
    text = _without_negated_sentences(description[:_TEXT_CHARS], r.agency_text_negations)
    if m := r.agency_text.search(text):
        return agency, f"text: '{_around(text, m)}'"
    ambiguous = None if excepted else r.agency_name_ambiguous.search(name)
    if ambiguous and (m := r.placement_text.search(text)):
        return agency, f"name: '{ambiguous.group(0)}' + text: '{_around(text, m)}'"
    return "employer", ""


def is_evergreen(title: str, description: str) -> bool:
    r = rules()
    return bool(
        r.evergreen_title.search(title) or r.evergreen_text.search(description[:_TEXT_CHARS])
    )


def _around(text: str, m: re.Match[str]) -> str:
    snippet = text[max(m.start() - 60, 0) : m.end() + 60]
    return "..." + " ".join(snippet.split()) + "..."


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
