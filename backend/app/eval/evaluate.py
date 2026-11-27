"""Phase 4 metrics from a label set's committed rankings (runs.jsonl) and one judge's
labels. Every number here is LLM-judged; the judge is named wherever it is reported.

Two conventions for jobs a variant ranked but no judge graded (the pool judged 20 jobs
per profile, fewer than the union of every variant's top 10):
- "unjudged0": an unjudged job counts as grade 0 (the metrics module's convention);
- "condensed": unjudged jobs are dropped from the ranking before scoring (Sakai's
  condensed lists, the usual remedy for incomplete judgements).
Each variant also reports judged@10, the share of its top 10 that was judged.

Rankings are the API's top 30 (pooling's LIMIT), so recall is Recall@30.
"""

import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from app.eval.metrics import (
    Estimate,
    bootstrap_ci,
    ndcg_at_k,
    paired_bootstrap,
    permutation_test,
    recall_at_k,
    reciprocal_rank,
)

Convention = Literal["unjudged0", "condensed"]
METRICS = ("ndcg10", "mrr", "recall30")
RECALL_K = 30
MODES = ("query", "profile")
# The pipeline, step by step (app/retrieval/service.py): two retrievers, RRF fusion, the
# personalised re-score, then the cross-encoder on the re-scored head.
STEPS = (
    ("keyword", "bm25"),
    ("vector", "vector"),
    ("hybrid", "fused"),
    ("+personalisation", "rescore"),
    ("+rerank 10@128", "rerank_10_128"),
    ("+rerank 20@128", "rerank_20_128"),
    ("+rerank 30@256", "rerank_30_256"),
)
RERANK_SETTINGS = ("rescore", "rerank_10_128", "rerank_20_128", "rerank_30_256")
# Single-search total latency on the owner's laptop, ms (docs/bench/search-2026-11-24.md,
# "Phase 4 candidates": same settings, 11,531-job pool, real models, one at a time).
LATENCY_MS: dict[str, dict[str, float]] = {
    "rescore": {"p50": 62.0, "p95": 74.8},
    "rerank_10_128": {"p50": 291.9, "p95": 331.1},
    "rerank_20_128": {"p50": 506.2, "p95": 593.3},
    "rerank_30_256": {"p50": 1588.2, "p95": 1817.2},
}
LATENCY_SOURCE = "docs/bench/search-2026-11-24.md (Phase 4 candidates, one search at a time)"
TARGET_P95_MS = 300.0
NDCG_MARGIN = 0.01


def load_runs(path: Path) -> dict[str, dict[str, list[str]]]:
    """variant -> profile -> job ids, best first."""
    runs: dict[str, dict[str, list[str]]] = {}
    with path.open(encoding="utf-8") as f:
        for line in f:
            if line.strip():
                row = json.loads(line)
                runs.setdefault(row["variant"], {})[row["profile_id"]] = row["job_ids"]
    return runs


def by_profile(labels: Mapping[str, int]) -> dict[str, dict[str, int]]:
    """pair id ("p01:<job id>") -> grade, regrouped as profile -> job id -> grade."""
    out: dict[str, dict[str, int]] = {}
    for pid, grade in labels.items():
        profile, job = pid.split(":", 1)
        out.setdefault(profile, {})[job] = grade
    return out


def profile_values(
    rankings: Mapping[str, Sequence[str]],
    grades: Mapping[str, Mapping[str, int]],
    convention: Convention,
) -> dict[str, dict[str, float]]:
    """metric -> profile -> value. Profiles with no judged job at grade >= 1 (NDCG) or
    >= 2 (recall) have no value for that metric; profiles with no judged job at all are
    skipped."""
    out: dict[str, dict[str, float]] = {m: {} for m in (*METRICS, "judged10")}
    for profile, ranked in rankings.items():
        judged = grades.get(profile, {})
        if not judged:
            continue
        top = list(ranked[:10])
        out["judged10"][profile] = sum(j in judged for j in top) / len(top) if top else 0.0
        ranked = [j for j in ranked if j in judged] if convention == "condensed" else ranked
        ndcg = ndcg_at_k(ranked, judged, 10)
        if ndcg is not None:
            out["ndcg10"][profile] = ndcg
        out["mrr"][profile] = reciprocal_rank(ranked, judged)
        recall = recall_at_k(ranked, judged, RECALL_K)
        if recall is not None:
            out["recall30"][profile] = recall
    return out


@dataclass(frozen=True)
class Diff:
    estimate: Estimate  # mean of a - b and its paired bootstrap CI
    p_value: float

    @property
    def verdict(self) -> str:
        if self.estimate.low > 0:
            return "better"
        if self.estimate.high < 0:
            return "worse"
        return "no clear difference"

    def as_dict(self) -> dict[str, Any]:
        return {**self.estimate.as_dict(), "p_value": self.p_value, "verdict": self.verdict}


def paired(a: Mapping[str, float], b: Mapping[str, float], seed: int = 0) -> Diff | None:
    common = sorted(set(a) & set(b))
    if len(common) < 2:
        return None
    xs, ys = [a[p] for p in common], [b[p] for p in common]
    return Diff(paired_bootstrap(xs, ys, seed=seed), permutation_test(xs, ys, seed=seed))


def comparisons(mode: str) -> list[tuple[str, str, str]]:
    """(name, variant a, variant b): a is compared with b."""
    label = {name: step for step, name in STEPS}

    def v(name: str) -> str:
        return f"{mode}:{name}"

    out = [
        ("hybrid vs vector", v("fused"), v("vector")),
        ("+personalisation vs hybrid", v("rescore"), v("fused")),
    ]
    out += [(f"{label[n]} vs +personalisation", v(n), v("rescore")) for n in RERANK_SETTINGS[1:]]
    out += [(f"{step} vs keyword", v(n), v("bm25")) for step, n in STEPS[1:]]
    return out


def evaluate(
    runs: Mapping[str, Mapping[str, Sequence[str]]],
    labels: Mapping[str, int],
    convention: Convention,
    *,
    seed: int = 0,
) -> dict[str, Any]:
    """Per variant: each metric's mean and bootstrap CI over profiles; then the paired
    comparisons of both modes and query vs profile mode."""
    grades = by_profile(labels)
    values = {v: profile_values(r, grades, convention) for v, r in runs.items()}
    variants: dict[str, Any] = {}
    for variant, per_metric in sorted(values.items()):
        variants[variant] = {
            m: bootstrap_ci(list(per_metric[m].values()), seed=seed).as_dict()
            if per_metric[m]
            else None
            for m in (*METRICS, "judged10")
        }
    compared: dict[str, Any] = {}
    for mode in MODES:
        for name, a, b in comparisons(mode):
            if a in values and b in values:
                compared[f"{mode}: {name}"] = {
                    m: (d.as_dict() if (d := paired(values[a][m], values[b][m], seed)) else None)
                    for m in METRICS
                }
    for _, name in STEPS:
        a, b = f"query:{name}", f"profile:{name}"
        if a in values and b in values:
            compared[f"query+profile vs profile only: {name}"] = {
                m: (d.as_dict() if (d := paired(values[a][m], values[b][m], seed)) else None)
                for m in METRICS
            }
    return {
        "convention": convention,
        "labelled_pairs": len(labels),
        "profiles": len(grades),
        "variants": variants,
        "comparisons": compared,
        "_values": values,
    }


def choose_rerank(result: Mapping[str, Any], mode: str = "query") -> dict[str, Any]:
    """ADR 0003 rule: among the rerank settings, those within NDCG_MARGIN NDCG@10 of the
    best mean, or whose CI overlaps the best's, are eligible; the one with the lowest
    single-search p95 is chosen. Says whether it meets the 300 ms target."""
    rows = []
    for name in RERANK_SETTINGS:
        est = result["variants"].get(f"{mode}:{name}", {}).get("ndcg10")
        if est is not None:
            rows.append((name, est))
    if not rows:
        return {"mode": mode, "chosen": None}
    best_name, best = max(rows, key=lambda r: r[1]["mean"])
    eligible = [
        name
        for name, est in rows
        if est["mean"] >= best["mean"] - NDCG_MARGIN
        or (est["ci_high"] >= best["ci_low"] and est["ci_low"] <= best["ci_high"])
    ]
    chosen = min(eligible, key=lambda n: LATENCY_MS[n]["p95"])
    return {
        "mode": mode,
        "best": best_name,
        "eligible": eligible,
        "chosen": chosen,
        "chosen_p95_ms": LATENCY_MS[chosen]["p95"],
        "meets_300ms": LATENCY_MS[chosen]["p95"] <= TARGET_P95_MS,
        "ndcg10": {name: est for name, est in rows},
        "latency_ms": {name: LATENCY_MS[name] for name, _ in rows},
        "latency_source": LATENCY_SOURCE,
    }


def holds(reference: str, other: str) -> str:
    """How a comparison's verdict under another judge relates to the reference's."""
    if other == reference:
        return "holds"
    if reference == "no clear difference" or other == "no clear difference":
        return "weaker" if reference != "no clear difference" else "differs"
    return "reverses"


def robustness(
    results: Mapping[str, Mapping[str, Any]],
    reference: str,
    names: Iterable[str],
    metric: str = "ndcg10",
) -> dict[str, Any]:
    """For each comparison: the verdict under every judge and whether it holds against
    the reference judge's verdict; plus the rerank setting each judge's labels choose."""
    out: dict[str, Any] = {"reference": reference, "metric": metric, "comparisons": {}}
    for name in names:
        row: dict[str, Any] = {}
        ref = results[reference]["comparisons"].get(name, {}).get(metric)
        for judge, result in results.items():
            d = result["comparisons"].get(name, {}).get(metric)
            if d is None:
                row[judge] = None
                continue
            row[judge] = {
                "mean": d["mean"],
                "ci_low": d["ci_low"],
                "ci_high": d["ci_high"],
                "verdict": d["verdict"],
                "vs_reference": holds(ref["verdict"], d["verdict"]) if ref else None,
            }
        out["comparisons"][name] = row
    out["rerank_choice"] = {
        judge: choose_rerank(result)["chosen"] for judge, result in results.items()
    }
    return out
