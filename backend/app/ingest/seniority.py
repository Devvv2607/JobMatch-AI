"""Seniority and employment type from rules over the title and source fields."""

import re

# Checked in order; the first match wins. Patterns run on the lower-cased title.
_SENIORITY_RULES: list[tuple[str, re.Pattern[str]]] = [
    ("intern", re.compile(r"\b(?:intern|internship|trainee|apprentice)\b")),
    ("executive", re.compile(r"\b(?:chief|cto|ceo|cfo|coo|cpo|ciso|vp|vice president|svp|evp)\b")),
    ("director", re.compile(r"\b(?:director|head of)\b")),
    ("principal", re.compile(r"\b(?:principal|distinguished|fellow)\b")),
    ("staff", re.compile(r"\bstaff\b")),
    # People managers only: "Product Manager", "Account Manager" and similar are ICs.
    (
        "manager",
        re.compile(
            r"^(?!.*\b(?:product|program|project|account|partner|community|"
            r"success|marketing|sales|office|territory|channel)\b)"
            r".*\b(?:manager|management)\b"
        ),
    ),
    ("lead", re.compile(r"\b(?:lead|tech lead|team lead)\b")),
    (
        "senior",
        re.compile(
            r"\b(?:senior|sr\.?|snr)\b|\b(?:iii|3)\s*$|\b(?:sde|swe|engineer)[- ]?(?:iii|3)\b"
        ),
    ),
    (
        "junior",
        re.compile(
            r"\b(?:junior|jr\.?|entry[- ]level|graduate|new grad|associate)\b|"
            r"\b(?:sde|swe|engineer)[- ]?(?:i|1)\b(?!\w)"
        ),
    ),
    ("mid", re.compile(r"\b(?:mid[- ]level|intermediate)\b|\b(?:sde|swe|engineer)[- ]?(?:ii|2)\b")),
]


def seniority_from_title(title: str) -> str:
    """One of intern, junior, mid, senior, lead, staff, principal, manager, director,
    executive. A title with no level marker ("Software Engineer") is "mid"."""
    lowered = title.lower()
    for level, pattern in _SENIORITY_RULES:
        if pattern.search(lowered):
            return level
    return "mid"


_EMPLOYMENT = [
    ("internship", re.compile(r"\bintern(?:ship)?s?\b", re.I)),
    ("contract", re.compile(r"contract|freelance|consultant|temporary|temp\b|fixed[- ]term", re.I)),
    ("part_time", re.compile(r"part[- _]?time", re.I)),
    ("full_time", re.compile(r"full[- _]?time|permanent|regular|fulltime", re.I)),
]


def employment_type(source_value: str | None, title: str) -> str:
    """From the source's field first, then the title. Default: full_time, which is what
    the overwhelming majority of untagged ATS postings are; flagged in the decision log."""
    for text in (source_value or "", title):
        for kind, pattern in _EMPLOYMENT:
            if pattern.search(text):
                return kind
    return "full_time"
