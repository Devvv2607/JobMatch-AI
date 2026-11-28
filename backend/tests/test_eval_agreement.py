"""Judge-vs-judge agreement (app/eval/agreement.py)."""

import pytest

from app.eval.agreement import (
    Facts,
    agreement_report,
    compare,
    confusion,
    majority,
    majority_stats,
    themes_of,
)

JUDGES = {
    "gemini": {"a": 3, "b": 2, "c": 1, "d": 0, "e": 2},
    "groq": {"a": 3, "b": 3, "c": 1, "d": 1},
    "cowork": {"a": 2, "b": 3, "c": 0, "d": 1, "e": 2},
}
IDS = ["a", "b", "c", "d", "e"]


def test_confusion_rows_are_the_first_judge() -> None:
    m = confusion([0, 1, 1, 3], [0, 2, 1, 3])
    assert m[1] == [0, 1, 1, 0]
    assert sum(map(sum, m)) == 4


def test_compare_uses_only_pairs_both_graded() -> None:
    r = compare("gemini", "groq", IDS, JUDGES)
    assert r.n == 4  # "e" has no Groq grade
    assert r.exact == 0.5
    assert r.within_one == 1.0
    assert r.mean_diff == pytest.approx(-0.5)
    assert r.top_cells == [(2, 3, 1), (0, 1, 1)]


def test_majority_is_the_median_of_three_and_needs_every_judge() -> None:
    assert majority(IDS, JUDGES) == {"a": 3, "b": 3, "c": 1, "d": 1}
    assert majority_stats(IDS, JUDGES) == {
        "two_agree": 4,
        "incomplete": 1,
    }
    with pytest.raises(ValueError, match="odd"):
        majority(IDS, {"gemini": JUDGES["gemini"], "groq": JUDGES["groq"]})


def test_themes_come_from_the_lower_judges_reason_and_the_posting_facts() -> None:
    assert themes_of({"employment": "freelance_gig"}, ["Right field."]) == {"gigs"}
    assert themes_of({}, ["Requires 5+ years; candidate is a fresher."]) == {"seniority"}
    assert themes_of({}, ["Not eligible outside the US."]) == {"location"}
    assert themes_of({}, ["No salary stated, a dealbreaker."]) == {"dealbreakers"}
    facts = Facts(
        strata={},
        reasons={
            "gemini": {"b": "Senior role for a junior candidate.", "d": "Different field."},
            "groq": {"b": "Great fit.", "d": "Only open to US residents (eligibility)."},
        },
    )
    r = compare("gemini", "groq", IDS, JUDGES, facts)
    # b: Gemini lower, its reason is about seniority. d: Gemini lower, no theme.
    assert r.themes["seniority"]["disagreements"] == 1
    assert r.themes["location"]["disagreements"] == 0
    assert r.themes["none of these"]["disagreements"] == 1
    assert r.themes["all disagreements"]["b_higher"] == 2


def test_report_has_every_pair_of_judges_and_the_majority() -> None:
    report = agreement_report(IDS, JUDGES)
    assert [(p["a"], p["b"]) for p in report["pairwise"]] == [
        ("gemini", "groq"),
        ("gemini", "cowork"),
        ("groq", "cowork"),
    ]
    assert report["graded"] == {"gemini": 5, "groq": 4, "cowork": 5}
    assert report["majority"]["pairs"] == 4
    two = agreement_report(IDS, {k: JUDGES[k] for k in ("gemini", "cowork")})
    assert "majority" not in two


def test_kappa_change_is_paired_and_only_improves_when_the_ci_excludes_zero() -> None:
    from app.eval.agreement import kappa_change

    ids = [f"p{i}" for i in range(40)]
    truth = {p: i % 4 for i, p in enumerate(ids)}
    noisy = {p: (g + 1) % 4 if i % 2 else g for i, (p, g) in enumerate(truth.items())}
    before = {"a": truth, "b": noisy}
    after = {"a": truth, "b": dict(truth)}  # b now agrees with a everywhere
    up = kappa_change(ids, "a", "b", after, before)
    assert up["n"] == 40 and up["delta"] > 0 and up["ci95"][0] > 0
    assert up["verdict"] == "improved"
    same = kappa_change(ids, "a", "b", before, before)
    assert same["delta"] == 0 and same["verdict"] == "no clear change"
    # Only pairs graded by both judges in both sets count.
    partial = {"a": truth, "b": {p: truth[p] for p in ids[:10]}}
    assert kappa_change(ids, "a", "b", partial, before)["n"] == 10
