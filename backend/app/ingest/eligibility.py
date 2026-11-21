"""Where a job can legally be done from. Rules only; no LLM.

Order:
1. On-site and hybrid jobs: structured ATS countries (Lever `country`, Ashby addresses).
2. Location fields (the ATS location strings, Remotive's candidate_required_location):
   worldwide phrases, regions, countries, cities, US states.
3. Remote jobs with a structured country but no usable location text: that country.
4. Description text rules ("must be based in the US", "work from anywhere", ...).
5. Otherwise unknown.

The result is stored per job (scope, countries, source). Eligibility for a candidate is
computed from it: worldwide -> eligible; listed -> eligible only if the candidate's
country is listed; unknown -> unknown.
"""

import re
from dataclasses import dataclass
from typing import Literal

from app.ingest.countries import gazetteer
from app.ingest.types import RawPosting

Scope = Literal["worldwide", "listed", "unknown"]
Eligibility = Literal["eligible", "ineligible", "unknown"]


@dataclass(frozen=True)
class WorkLocation:
    scope: Scope
    countries: tuple[str, ...]
    source: str  # which field or rule decided

    def eligibility_for(self, country: str) -> Eligibility:
        if self.scope == "worldwide":
            return "eligible"
        if self.scope == "listed":
            return "eligible" if country.upper() in self.countries else "ineligible"
        return "unknown"


UNKNOWN = WorkLocation("unknown", (), "none")

# What `RawPosting.location_restriction` holds for each source, for the source label.
_RESTRICTION_FIELD = {
    "greenhouse": "greenhouse.offices",
    "remotive": "remotive.candidate_required_location",
}

_SPLIT = re.compile(r"\s*(?:[|;/,()\[\]&]|\s-\s|\s–\s|\s—\s|\bor\b|\band\b|\+(?!\d))\s*", re.I)
_NOISE = re.compile(
    r"^(?:remote|remotely|hybrid|on-?site|in-?office|office|fully remote|remote-first|"
    r"flexible|multiple locations|various|distributed|based|hq|headquarters|only|"
    r"timezones?|time zones?|preferred|friendly|first|n/?a)$",
    re.I,
)
_REMOTE_PREFIX = re.compile(r"^(?:remote|hybrid|on-?site)\s*[:\-–]?\s*", re.I)
# "California Remote", "Singapore Office", "Berlin only": a place followed by a qualifier.
_QUALIFIER_SUFFIX = re.compile(
    r"\s+(?:only|timezones?|time zones?|based|preferred|remote|office|hq)$", re.I
)
# "IN-Bengaluru", "CA-Toronto", "MX- Mexico City": a country code glued to a place.
_CODE_PREFIX = re.compile(r"^([a-z]{2})-\s*(.+)$")


def parse_location(text: str) -> tuple[Scope, frozenset[str], str] | None:
    """Parses one location string. Returns None if nothing in it names a place."""
    g = gazetteer()
    lowered = " ".join(text.lower().split())
    if lowered in g.worldwide:
        return "worldwide", frozenset(), "worldwide"

    countries: set[str] = set()
    kinds: set[str] = set()
    parts = [p for p in _SPLIT.split(lowered) if p and p.strip()]
    segments = [s.strip() for s in lowered.split(",")]
    for part in parts:
        token = _REMOTE_PREFIX.sub("", part.strip()).strip(" .")
        token = _QUALIFIER_SUFFIX.sub("", token)
        known = token in g.cities or token in g.countries or token in g.regions
        if not known and (glued := _CODE_PREFIX.match(token)) and glued.group(1).upper() in g.codes:
            token = glued.group(2).strip()
        if not token or _NOISE.match(token):
            continue
        if token in g.worldwide:
            return "worldwide", frozenset(), "worldwide"
        if token in g.regions:
            countries |= g.regions[token]
            kinds.add("region")
        elif (code := g.countries.get(token)) is not None:
            countries.add(code)
            kinds.add("country")
        elif token.upper() in g.codes and len(token) == 2 and token not in g.us_state_abbreviations:
            countries.add(token.upper())
            kinds.add("country")
        elif token in g.cities:
            countries.add(g.cities[token])
            kinds.add("city")
        elif token in g.us_state_names:
            countries.add("US")
            kinds.add("us_state")
    # "Austin, TX": a state abbreviation as the last comma-separated part.
    if not countries and len(segments) >= 2 and segments[-1] in g.us_state_abbreviations:
        countries.add("US")
        kinds.add("us_state")
    if not countries:
        return None
    kind = "region" if "region" in kinds else sorted(kinds)[0]
    return "listed", frozenset(countries), kind


def from_locations(texts: list[str], field: str) -> WorkLocation | None:
    """Union over a job's location strings. Any worldwide entry makes the job worldwide."""
    found: set[str] = set()
    kinds: list[str] = []
    for text in texts:
        parsed = parse_location(text)
        if parsed is None:
            continue
        scope, countries, kind = parsed
        if scope == "worldwide":
            return WorkLocation("worldwide", (), f"location:{field}:worldwide")
        found |= countries
        kinds.append(kind)
    if not found:
        return None
    kind = "region" if "region" in kinds else kinds[0]
    return WorkLocation("listed", tuple(sorted(found)), f"location:{field}:{kind}")


# Description rules: (name, pattern, scope, countries). First match wins, in order.
_TEXT_RULES: list[tuple[str, re.Pattern[str], Scope, tuple[str, ...]]] = [
    (
        "worldwide",
        re.compile(
            r"\b(?:work from anywhere|anywhere in the world|from any country|"
            r"(?:hire|hiring|open to (?:candidates|applicants|people)) (?:from )?"
            r"(?:anywhere|globally|worldwide|around the world))\b",
            re.I,
        ),
        "worldwide",
        (),
    ),
    (
        "india",
        re.compile(
            r"\b(?:(?:must|should|need to) be (?:based|located|residing) in india|"
            r"(?:candidates|applicants) (?:based )?in india|"
            r"remote(?:ly)?,? (?:from |within |in )?india|"
            r"india[- ]based (?:candidates|applicants|role))\b",
            re.I,
        ),
        "listed",
        ("IN",),
    ),
    (
        "us_only",
        re.compile(
            r"\b(?:(?:must|should|need to) (?:be|reside|live) (?:based |located |residing )?in "
            r"the (?:us|u\.s\.|united states)|"
            r"(?:legally )?authori[sz]ed to work in the (?:us|u\.s\.|united states)|"
            r"(?:us|u\.s\.)[- ]based (?:candidates|applicants) only|"
            r"open (?:only )?to (?:us|u\.s\.|united states) (?:residents|citizens|candidates)|"
            r"remote (?:within|in) the (?:us|u\.s\.|united states))\b",
            re.I,
        ),
        "listed",
        ("US",),
    ),
]


def from_description(text: str) -> WorkLocation | None:
    for name, pattern, scope, countries in _TEXT_RULES:
        if pattern.search(text):
            return WorkLocation(scope, countries, f"description:{name}")
    return None


def work_location(posting: RawPosting, description_text: str) -> WorkLocation:
    structured = (
        WorkLocation(
            "listed",
            tuple(sorted(set(posting.structured_countries))),
            posting.structured_country_field or "structured",
        )
        if posting.structured_countries
        else None
    )
    if structured is not None and posting.workplace in ("onsite", "hybrid"):
        return structured

    located = from_locations(list(posting.locations), f"{posting.source}.location")
    if located is None and posting.location_restriction:
        located = from_locations(
            [posting.location_restriction], _RESTRICTION_FIELD.get(posting.source, "restriction")
        )
    if located is not None:
        return located
    if structured is not None:
        return structured
    return from_description(description_text) or UNKNOWN
