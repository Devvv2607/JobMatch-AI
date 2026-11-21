"""Fusion, re-score and explanation: pure functions."""

import uuid

import pytest
from pydantic import ValidationError

from app.retrieval.schemas import SearchRequest
from app.retrieval.scoring import (
    Components,
    JobFacts,
    Preferences,
    SearchProfile,
    Weights,
    experience_fit,
    explain,
    final_score,
    preference_matches,
    preference_score,
    rrf,
    sigmoid,
    skill_match,
)

A, B, C, D = (uuid.uuid4() for _ in range(4))
W = Weights(rerank=0.6, skills=0.25, experience=0.1, preferences=0.05)


def facts(**overrides: object) -> JobFacts:
    values: dict[str, object] = {
        "skills": ["Python", "PostgreSQL", "Kubernetes"],
        "seniority": "senior",
        "remote_policy": "remote",
        "work_countries": [],
        "eligibility_scope": "worldwide",
    }
    values.update(overrides)
    return JobFacts(**values)  # type: ignore[arg-type]


def test_rrf_sums_reciprocal_ranks_and_rewards_agreement() -> None:
    fused = dict(rrf([[A, B, C], [B, D]], k=60))
    assert fused[B] == pytest.approx(1 / 62 + 1 / 61)
    assert fused[A] == pytest.approx(1 / 61)
    assert fused[D] == pytest.approx(1 / 62)
    assert [job for job, _ in rrf([[A, B, C], [B, D]], k=60)][:1] == [B]


def test_rrf_ties_keep_first_seen_order_and_empty_lists_are_fine() -> None:
    assert [job for job, _ in rrf([[A], [B]], k=60)] == [A, B]
    assert rrf([[], []], k=60) == []


def test_sigmoid_is_stable_for_large_logits() -> None:
    assert sigmoid(0) == 0.5
    assert sigmoid(800) == 1.0
    assert sigmoid(-800) == 0.0


def test_skills_are_compared_by_canonical_name() -> None:
    profile = SearchProfile(skills=["postgres", "python", "Rust"])
    match = skill_match(profile, ["Python", "PostgreSQL", "Kubernetes"])
    assert match.matched == ["Python", "PostgreSQL"]
    assert match.missing == ["Kubernetes"]
    assert match.coverage == pytest.approx(2 / 3)


def test_skill_coverage_is_unknown_without_profile_skills_or_posting_skills() -> None:
    assert skill_match(None, ["Python"]).coverage is None
    assert skill_match(SearchProfile(skills=["Python"]), []).coverage is None


@pytest.mark.parametrize(
    ("years", "fit", "score"),
    [(7, "within", 1.0), (3, "below", 0.5), (12, "above", 0.5), (0, "below", 0.0)],
)
def test_experience_fit_against_the_level_band(years: float, fit: str, score: float) -> None:
    result, value = experience_fit(SearchProfile(years_experience=years), "senior")
    assert result.expected_years == (5, 10)
    assert result.fit == fit
    assert value == pytest.approx(score)


def test_experience_is_unknown_without_years() -> None:
    result, value = experience_fit(SearchProfile(), "senior")
    assert (result.fit, value) == ("unknown", None)


def test_preferences_score_one_zero_or_half_when_the_posting_is_silent() -> None:
    profile = SearchProfile(
        preferences=Preferences(workplace=["remote"], countries=["India"], seniority=["mid"])
    )
    matches = preference_matches(
        profile, facts(remote_policy="unknown", eligibility_scope="listed", work_countries=["IN"])
    )
    assert [(m.name, m.match) for m in matches] == [
        ("workplace", None),
        ("countries", True),
        ("seniority", False),
    ]
    assert preference_score(matches) == pytest.approx((0.5 + 1 + 0) / 3)
    assert preference_score([]) is None


def test_final_score_is_the_weighted_mean_of_available_components_only() -> None:
    only_rerank = Components(rerank=0.8, skills=None, experience=None, preferences=None)
    assert final_score(only_rerank, W) == pytest.approx(0.8)
    full = Components(rerank=0.8, skills=0.5, experience=1.0, preferences=0.0)
    assert final_score(full, W) == pytest.approx(0.6 * 0.8 + 0.25 * 0.5 + 0.1 * 1.0)


def test_explain_builds_the_object_from_structured_fields() -> None:
    profile = SearchProfile(skills=["Python"], years_experience=6)
    explanation, components = explain(profile, facts(), 0.0, flags=[])
    assert explanation.skills.matched == ["Python"]
    assert explanation.skills.missing == ["PostgreSQL", "Kubernetes"]
    assert explanation.experience.fit == "within"
    assert components.rerank == 0.5


def test_a_request_needs_a_query_or_profile_skills() -> None:
    with pytest.raises(ValidationError):
        SearchRequest()
    with pytest.raises(ValidationError):
        SearchRequest(query="   ", profile=SearchProfile(years_experience=3))
    request = SearchRequest(profile=SearchProfile(skills=["postgres", "Python", "python"]))
    assert request.query_text() == "PostgreSQL Python"
    assert SearchRequest(query="  data   engineer ").query_text() == "data engineer"


def test_unknown_rule_kinds_and_countries_are_rejected() -> None:
    with pytest.raises(ValidationError):
        SearchRequest.model_validate({"query": "x", "rules": [{"kind": "astrology"}]})
    with pytest.raises(ValidationError):
        SearchRequest.model_validate(
            {"query": "x", "rules": [{"kind": "work_eligibility", "country": "Atlantis"}]}
        )
