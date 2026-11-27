"""Phase 4 metrics over rankings and one judge's labels (app/eval/evaluate.py)."""

import json
from pathlib import Path

import pytest

from app.eval.evaluate import (
    by_profile,
    choose_rerank,
    evaluate,
    holds,
    load_runs,
    profile_values,
    robustness,
)


def test_load_runs_and_regroup_labels(tmp_path: Path) -> None:
    path = tmp_path / "runs.jsonl"
    rows = [
        {"profile_id": "p01", "variant": "query:bm25", "job_ids": ["a", "b"]},
        {"profile_id": "p02", "variant": "query:bm25", "job_ids": ["c"]},
    ]
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))
    assert load_runs(path) == {"query:bm25": {"p01": ["a", "b"], "p02": ["c"]}}
    assert by_profile({"p01:a": 3, "p01:b": 0, "p02:c": 2}) == {
        "p01": {"a": 3, "b": 0},
        "p02": {"c": 2},
    }


def test_condensed_drops_unjudged_jobs_before_scoring() -> None:
    grades = {"p01": {"a": 3, "b": 2}}
    rankings = {"p01": ["x", "y", "a", "b"]}  # x, y never judged
    zero = profile_values(rankings, grades, "unjudged0")
    condensed = profile_values(rankings, grades, "condensed")
    assert zero["judged10"]["p01"] == 0.5
    assert zero["mrr"]["p01"] == pytest.approx(1 / 3)
    assert condensed["mrr"]["p01"] == 1.0
    assert condensed["ndcg10"]["p01"] == pytest.approx(1.0)
    assert zero["ndcg10"]["p01"] < 1.0
    assert profile_values(rankings, {}, "condensed")["ndcg10"] == {}


def runs_for(profiles: int) -> dict[str, dict[str, list[str]]]:
    """bm25 puts the relevant job last, every other variant first."""
    names = ("bm25", "vector", "fused", "rescore", "rerank_10_128", "rerank_20_128")
    out: dict[str, dict[str, list[str]]] = {}
    for mode in ("query", "profile"):
        for name in (*names, "rerank_30_256"):
            out[f"{mode}:{name}"] = {
                f"p{i:02d}": ["bad", "good"] if name == "bm25" else ["good", "bad"]
                for i in range(profiles)
            }
    return out


LABELS = {f"p{i:02d}:{job}": g for i in range(6) for job, g in (("good", 3), ("bad", 0))}


def test_evaluate_reports_cis_and_paired_comparisons() -> None:
    result = evaluate(runs_for(6), LABELS, "condensed")
    assert result["profiles"] == 6
    assert result["variants"]["query:fused"]["ndcg10"]["mean"] == pytest.approx(1.0)
    vs = result["comparisons"]["query: hybrid vs keyword"]["ndcg10"]
    assert vs["mean"] > 0 and vs["verdict"] == "better"
    assert result["comparisons"]["query: hybrid vs vector"]["ndcg10"]["verdict"] == (
        "no clear difference"
    )
    assert "query+profile vs profile only: fused" in result["comparisons"]


def test_rerank_rule_takes_the_cheapest_setting_not_worse_than_the_best() -> None:
    runs = runs_for(6)
    # No rerank puts the relevant job second for every profile: clearly worse (paired).
    runs["query:rescore"] = {p: ["bad", "good"] for p in runs["query:rescore"]}
    choice = choose_rerank(evaluate(runs, LABELS, "condensed"))
    assert choice["best"] == "rerank_10_128"
    assert choice["eligible"] == ["rerank_10_128", "rerank_20_128", "rerank_30_256"]
    assert choice["difference_to_best"]["rescore"]["verdict"] == "worse"
    assert choice["chosen"] == "rerank_10_128"
    assert choice["meets_300ms"] is False  # 331 ms p95
    # Worse for only one profile of six: the paired CI includes 0, so no rerank is
    # eligible and, being cheapest, chosen.
    runs["query:rescore"] = {p: ["good", "bad"] for p in runs["query:rescore"]}
    runs["query:rescore"]["p00"] = ["bad", "good"]
    choice = choose_rerank(evaluate(runs, LABELS, "condensed"))
    assert choice["chosen"] == "rescore"
    assert choice["meets_300ms"] is True


def test_holds_compares_verdicts_with_the_reference() -> None:
    assert holds("better", "better") == "holds"
    assert holds("better", "no clear difference") == "weaker"
    assert holds("no clear difference", "better") == "differs"
    assert holds("better", "worse") == "reverses"


def test_robustness_lists_every_judge_per_comparison() -> None:
    runs = runs_for(6)
    flipped = {pid: 3 - g for pid, g in LABELS.items()}
    results = {
        "gemini": evaluate(runs, LABELS, "condensed"),
        "other": evaluate(runs, flipped, "condensed"),
    }
    out = robustness(results, "gemini", ["query: hybrid vs keyword"])
    row = out["comparisons"]["query: hybrid vs keyword"]
    assert row["gemini"]["vs_reference"] == "holds"
    assert row["other"]["vs_reference"] == "reverses"
    assert set(out["rerank_choice"]) == {"gemini", "other"}
