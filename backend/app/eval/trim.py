# ruff: noqa: RUF001 - the patterns match the typographic apostrophe and en dash on purpose
"""Judge input v3: section-aware trimming of a job description (owner decision 2026-11-27).

Input v2 sent the first ~1,400 characters of the card's description (app/eval/judge.py
`lead`). The card text is already the company-boilerplate-stripped `search_text`
(app/ingest/boilerplate.py, the EMBED_TEXT_VERSION stripper). v2 often cut off the
requirements: in 323 of 1,000 pairs, the first years-of-experience statement came after
the cut. v3 keeps what decides a grade:

1. Text at or under V2_CHARS is returned unchanged, so it matches v2 exactly.
2. Otherwise the description is split into paragraphs, each assigned to the section of
   the latest heading above it (a short paragraph that names a section). Paragraphs are
   kept by priority, each within the character cap:
   1. requirements / qualifications sections (headings included);
   2. any other paragraph that states years of experience or a seniority level;
   3. responsibilities sections;
   4. everything else (an untitled intro, other sections);
   then generic boilerplate sections (company intro, benefits, equal opportunity,
   how to apply) are dropped first, kept only if room is left.
   A priority-1 or -2 paragraph that does not fit whole is cut at a word, if at least
   MIN_PIECE characters fit. Kept paragraphs stay in their original order, and "[…]"
   marks each gap.
"""

import re

from app.ingest.boilerplate import paragraphs

V2_CHARS = 1400  # judge input v2's limit (app/eval/judge.py DESCRIPTION_CHARS)
MIN_PIECE = 200
GAP = "[…]"

REQUIREMENTS = re.compile(
    r"requirement|qualification|what you['’]?ll (?:need|bring)|what you bring|"
    r"what we['’]?re looking for|who you are|about you|you (?:have|bring|should have|will have)|"
    r"must[- ]haves?|nice[- ]to[- ]haves?|preferred|skills|experience|ideal candidate|"
    r"eligibility|you['’]?re a (?:great )?fit|what you need",
    re.I,
)
RESPONSIBILITIES = re.compile(
    r"responsibilit|what you['’]?ll do|what you will do|the role|your role|in this role|"
    r"day[- ]to[- ]day|key (?:duties|tasks)|duties|what you['’]?ll be doing|the job|"
    r"your impact|what you['’]?ll work on|the opportunity|job description|role overview",
    re.I,
)
BOILERPLATE = re.compile(
    r"about (?:us|the company|the team|[A-Z][\w&.\- ]{0,40})$|who we are|"
    r"our (?:story|mission|culture)|"
    r"benefits|perks|what we offer|why (?:join|work)|equal (?:employment )?opportunit|"
    r"\beeo\b|diversity|accommodation|privacy|how to apply|application process|to apply|"
    r"recruitment process|hiring process|interview process",
    re.I,
)
EXPERIENCE = re.compile(
    r"\b\d+\s*\+?\s*(?:-|–|to)?\s*\d*\s*\+?\s*(?:years?|yrs?)\b|"
    r"years? of (?:\w+ ){0,2}experience|"
    r"\b(?:senior|junior|mid[- ]level|entry[- ]level|staff|principal|lead|fresher|graduate|"
    r"intern(?:ship)?|seniority)\b",
    re.I,
)
HEADING_MAX = 80


def heading_kind(paragraph: str) -> str | None:
    """The section a heading opens, or None if the paragraph is not a heading."""
    text = paragraph.strip().strip("*#:").strip()
    if not text or len(text) > HEADING_MAX or "\n" in text:
        return None
    if not (paragraph.rstrip().endswith(":") or len(text.split()) <= 8):
        return None
    # Requirements and responsibilities first: "About you" and "About the role" are not
    # boilerplate, though "About <Company>" is.
    for kind, rx in (
        ("requirements", REQUIREMENTS),
        ("responsibilities", RESPONSIBILITIES),
        ("boilerplate", BOILERPLATE),
    ):
        if rx.search(text):
            return kind
    return None


def _cut(text: str, limit: int) -> str:
    cut = text[:limit]
    return (cut[: cut.rfind(" ")] if " " in cut else cut).rstrip() + " …"


def trim(description: str, cap: int) -> str:
    """Judge input v3 for one description (see the module docstring)."""
    if len(description) <= V2_CHARS:
        return description
    parts = paragraphs(description)
    section = "rest"
    priority: list[int] = []
    for p in parts:
        kind = heading_kind(p)
        if kind is not None:
            section = kind
        if section == "requirements":
            priority.append(1)
        elif section != "boilerplate" and EXPERIENCE.search(p):
            priority.append(2)
        elif section == "responsibilities":
            priority.append(3)
        elif section == "rest":
            priority.append(4)
        else:
            priority.append(5)
    kept: dict[int, str] = {}
    used = 0
    for level in (1, 2, 3, 4, 5):
        for i, p in enumerate(parts):
            if priority[i] != level:
                continue
            cost = len(p) + 2
            if used + cost <= cap:
                kept[i] = p
                used += cost
            elif level <= 2 and cap - used - 2 >= MIN_PIECE:
                kept[i] = _cut(p, cap - used - 4)
                used = cap
    out: list[str] = []
    for i in range(len(parts)):
        if i in kept:
            out.append(kept[i])
        elif not out or out[-1] != GAP:
            out.append(GAP)
    return "\n\n".join(out)
