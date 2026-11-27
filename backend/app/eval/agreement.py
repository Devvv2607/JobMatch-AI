"""Judge-vs-judge agreement (owner decision 2026-11-27: the set is LLM-judged only).

Three LLM judges grade with the same rubric: Gemini (primary, all pairs), Groq (the 120
blind pairs) and Claude Cowork (an AI agent, graded in sheets). For each pair of judges,
over the pairs both graded: quadratic weighted kappa, exact and within-one agreement, the
4x4 confusion matrix and the mean grade difference. On pairs all three graded, the
majority grade is the median of the three (with three ordinal grades the median is the
grade at least two judges are at or beyond; when all three differ it is the middle one).

Disagreement themes: for each pair two judges grade differently, the reason of the judge
that graded lower (the one naming the defect) is tagged, together with the posting's facts:
- dealbreakers: names a dealbreaker or salary/pay;
- seniority: names the level, seniority, a years-of-experience requirement or a stretch;
- location: names location, eligibility, onsite/relocation, a country or a visa;
- gigs: the posting is a freelance gig, contract or agency posting, or the reason names
  gig, annotation, rating or AI-training work.
A disagreement can carry several themes or none. Each theme is reported as a share of the
disagreements, with which judge graded higher.
"""

import random
import re
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from itertools import combinations
from pathlib import Path
from typing import Any

from app.eval.metrics import quantile, weighted_kappa
from app.eval.pairs import JudgeRecord, load_judge

# Judge name -> file in the set folder. Gemini is the primary judge.
JUDGES: dict[str, str] = {
    "gemini": "judge.jsonl",
    "groq": "judge-groq-blind.jsonl",
    "cowork": "judge-claude-cowork.jsonl",
}
GRADES = range(4)
THEMES: dict[str, re.Pattern[str]] = {
    "dealbreakers": re.compile(r"deal-?breaker|salary|pay\b|compensation", re.I),
    "seniority": re.compile(
        r"senior|junior|seniority|over-?qualif|under-?qualif|\bstaff\b|principal|fresher"
        r"|entry[- ]level|\blevel\b|stretch|years of|\d\+? ?years",
        re.I,
    ),
    "location": re.compile(
        r"locat|eligib|on-?site|relocat|visa|countr|based in|time ?zone|outside", re.I
    ),
    "gigs": re.compile(r"\bgigs?\b|annotat|rating|ai[- ]training|per-task|freelance", re.I),
}
GIG_STRATA = {("employment", "freelance_gig"), ("employment", "contract")}
AGENCY_STRATA = {("poster", "staffing_agency")}


def load_judges(folder: Path, judges: Mapping[str, str] = JUDGES) -> dict[str, dict[str, int]]:
    return {name: grades(load_judge(folder / file)) for name, file in judges.items()}


def grades(records: Mapping[str, JudgeRecord]) -> dict[str, int]:
    return {pid: r.label for pid, r in records.items()}


def load_reasons(folder: Path, judges: Mapping[str, str] = JUDGES) -> dict[str, dict[str, str]]:
    """judge -> pair id -> reason."""
    return {
        name: {pid: r.reason for pid, r in load_judge(folder / file).items()}
        for name, file in judges.items()
    }


def confusion(a: Iterable[int], b: Iterable[int]) -> list[list[int]]:
    """matrix[i][j]: pairs the first judge graded i and the second graded j."""
    matrix = [[0] * len(GRADES) for _ in GRADES]
    for x, y in zip(a, b, strict=True):
        matrix[x][y] += 1
    return matrix


@dataclass
class PairAgreement:
    a: str
    b: str
    n: int
    kappa: float | None
    exact: float
    within_one: float
    mean_diff: float  # mean of a - b
    matrix: list[list[int]]
    kappa_ci: tuple[float, float] | None = None  # 95% percentile bootstrap over pairs
    themes: dict[str, dict[str, Any]] = field(default_factory=dict)
    top_cells: list[tuple[int, int, int]] = field(default_factory=list)  # (a, b, count)

    def as_dict(self) -> dict[str, Any]:
        return {
            "a": self.a,
            "b": self.b,
            "n": self.n,
            "weighted_kappa": self.kappa,
            "weighted_kappa_ci95": list(self.kappa_ci) if self.kappa_ci else None,
            "exact": self.exact,
            "within_one": self.within_one,
            "mean_diff_a_minus_b": self.mean_diff,
            "confusion_rows_a_cols_b": self.matrix,
            "themes": self.themes,
            "most_common_disagreements": [
                {"a": x, "b": y, "pairs": n} for x, y, n in self.top_cells
            ],
        }


def kappa_ci(
    xs: Sequence[int], ys: Sequence[int], *, resamples: int = 2000, seed: int = 0
) -> tuple[float, float]:
    """95% percentile bootstrap CI of the weighted kappa, resampling pairs."""
    rng = random.Random(seed)  # noqa: S311 - reproducible resampling, not security
    n = len(xs)
    values = []
    for _ in range(resamples):
        idx = [rng.randrange(n) for _ in range(n)]
        values.append(weighted_kappa([xs[i] for i in idx], [ys[i] for i in idx]))
    values.sort()
    return quantile(values, 0.025), quantile(values, 0.975)


def themes_of(strata: Mapping[str, str], reasons: Iterable[str]) -> set[str]:
    found = {name for name, rx in THEMES.items() if any(rx.search(r) for r in reasons)}
    facts = set(strata.items())
    if facts & GIG_STRATA or facts & AGENCY_STRATA:
        found.add("gigs")
    return found


@dataclass(frozen=True)
class Facts:
    """What the theme tagging reads: each pair's strata and each judge's reasons."""

    strata: Mapping[str, Mapping[str, str]]
    reasons: Mapping[str, Mapping[str, str]]

    def themes(self, pid: str, judge: str) -> set[str]:
        reason = self.reasons.get(judge, {}).get(pid, "")
        return themes_of(self.strata.get(pid, {}), [reason])


def compare(
    a: str,
    b: str,
    ids: Iterable[str],
    judges: Mapping[str, Mapping[str, int]],
    facts: Facts | None = None,
) -> PairAgreement:
    both = [pid for pid in ids if pid in judges[a] and pid in judges[b]]
    xs = [judges[a][pid] for pid in both]
    ys = [judges[b][pid] for pid in both]
    n = len(both)
    result = PairAgreement(
        a=a,
        b=b,
        n=n,
        kappa=weighted_kappa(xs, ys) if n >= 2 else None,
        kappa_ci=kappa_ci(xs, ys) if n >= 2 else None,
        exact=sum(x == y for x, y in zip(xs, ys, strict=True)) / n if n else 0.0,
        within_one=sum(abs(x - y) <= 1 for x, y in zip(xs, ys, strict=True)) / n if n else 0.0,
        mean_diff=sum(x - y for x, y in zip(xs, ys, strict=True)) / n if n else 0.0,
        matrix=confusion(xs, ys),
    )
    off = Counter((x, y) for x, y in zip(xs, ys, strict=True) if x != y)
    result.top_cells = [(x, y, c) for (x, y), c in off.most_common(5)]
    if facts is not None and n:
        differ = [pid for pid in both if judges[a][pid] != judges[b][pid]]
        lower = {pid: a if judges[a][pid] < judges[b][pid] else b for pid in differ}
        tagged = {pid: facts.themes(pid, lower[pid]) for pid in differ}
        groups = {theme: [p for p in differ if theme in tagged[p]] for theme in THEMES}
        groups["none of these"] = [p for p in differ if not tagged[p]]
        groups["all disagreements"] = differ
        for theme, members in groups.items():
            # Examples: the widest gaps first, then pair id (deterministic).
            ordered = sorted(members, key=lambda p: (-abs(judges[a][p] - judges[b][p]), p))
            result.themes[theme] = {
                "disagreements": len(members),
                "share": len(members) / len(differ) if differ else 0.0,
                "a_higher": sum(judges[a][p] > judges[b][p] for p in members),
                "b_higher": sum(judges[a][p] < judges[b][p] for p in members),
                "examples": [
                    {
                        "pair_id": p,
                        a: judges[a][p],
                        b: judges[b][p],
                        "lower": lower[p],
                        "lower_reason": facts.reasons.get(lower[p], {}).get(p, ""),
                    }
                    for p in ordered[:3]
                ]
                if theme != "all disagreements"
                else [],
            }
    return result


def majority(ids: Iterable[str], judges: Mapping[str, Mapping[str, int]]) -> dict[str, int]:
    """The median grade of the pairs every judge graded (odd number of judges)."""
    if len(judges) % 2 == 0:
        raise ValueError("a majority needs an odd number of judges")
    out = {}
    for pid in ids:
        gs = [g[pid] for g in judges.values() if pid in g]
        if len(gs) == len(judges):
            out[pid] = sorted(gs)[len(gs) // 2]
    return out


def majority_stats(ids: Iterable[str], judges: Mapping[str, Mapping[str, int]]) -> dict[str, int]:
    stats = Counter[str]()
    for pid in ids:
        gs = [g[pid] for g in judges.values() if pid in g]
        if len(gs) != len(judges):
            stats["incomplete"] += 1
        elif len(set(gs)) == 1:
            stats["unanimous"] += 1
        elif len(set(gs)) == len(gs):
            stats["all_differ"] += 1
        else:
            stats["two_agree"] += 1
    return dict(stats)


def agreement_report(
    ids: list[str],
    judges: Mapping[str, Mapping[str, int]],
    facts: Facts | None = None,
) -> dict[str, Any]:
    """Every pair of judges over `ids`, plus the majority over the pairs all graded."""
    pairs = [compare(a, b, ids, judges, facts) for a, b in combinations(judges, 2)]
    report: dict[str, Any] = {
        "pairs": len(ids),
        "graded": {name: sum(pid in g for pid in ids) for name, g in judges.items()},
        "pairwise": [p.as_dict() for p in pairs],
    }
    if len(judges) % 2 == 1 and len(judges) > 1:
        report["majority"] = majority_stats(ids, judges)
        report["majority"]["pairs"] = len(majority(ids, judges))
    return report
