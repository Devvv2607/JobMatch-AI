"""The 25 fictional evaluation profiles (eval/profiles/) load, validate as search requests,
and follow the brief's mix (docs/briefs/phase-4.md, item 2)."""

import re
from collections import Counter

from app.eval.profiles import load_profiles
from app.retrieval.rules import WorkEligibility

PROFILES = load_profiles()


def test_there_are_25_profiles_p01_to_p25() -> None:
    assert sorted(PROFILES) == [f"p{i:02d}" for i in range(1, 26)]


def test_about_70_percent_india_and_every_band_and_field_covered() -> None:
    regions = Counter(p.region for p in PROFILES.values())
    assert regions["india"] == 18  # 72%
    assert regions["us"] + regions["eu"] + regions["remote"] == 7
    india = [p for p in PROFILES.values() if p.region == "india"]
    assert {p.experience_band for p in india} == {"fresher", "1-3", "3-6"}
    assert {p.field for p in india} == {"ml_ai", "data", "backend", "full_stack", "product_analyst"}
    # Every (field, band) cell has at least one India profile.
    cells = {(p.field, p.experience_band) for p in india}
    assert len(cells) == 15


def test_every_profile_is_a_valid_search_request_both_ways() -> None:
    for p in PROFILES.values():
        assert p.search_request().query == p.query
        assert p.search_request(with_query=False).query is None  # profile-only variant
        assert p.profile.skills


def test_every_profile_can_work_where_it_says_and_says_where() -> None:
    for p in PROFILES.values():
        eligibility = [r for r in p.rules if isinstance(r, WorkEligibility)]
        assert len(eligibility) == 1, p.id
        assert [eligibility[0].country] == p.profile.preferences.countries, p.id


def test_years_match_the_experience_band() -> None:
    bands = {"fresher": (0, 1), "1-3": (1, 3.5), "3-6": (3.5, 6.5)}
    for p in PROFILES.values():
        low, high = bands[p.experience_band]
        assert p.profile.years_experience is not None
        assert low <= p.profile.years_experience <= high, p.id


def test_no_contact_details_or_names_in_personas() -> None:
    contact = re.compile(r"@|\+?\d[\d\s-]{8,}\d|linkedin|github\.com/", re.I)
    for p in PROFILES.values():
        assert not contact.search(p.persona), p.id
        # Personas speak about "the candidate" without a name: no capitalised first word
        # followed by a capitalised surname at the start.
        assert not re.match(r"^[A-Z][a-z]+ [A-Z][a-z]+ (?:is|has|was)\b", p.persona), p.id
