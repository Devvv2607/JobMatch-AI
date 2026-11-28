"""Ranking metrics over judged pairs, with uncertainty over profiles.

Grades are 0-3 (the rubric in app/prompts/eval_judge). Conventions, stated in every
report:
- A job a variant ranked but nobody judged counts as grade 0 (pooling judges the top of
  every variant, so this only affects ranks below the pooled depth).
- NDCG@k uses gain 2^grade - 1 and discount log2(rank + 1); the ideal ranking is built
  from every judged pair of that profile. A profile with no judged job above grade 0
  has no NDCG (excluded, and counted).
- MRR and Recall@k call a job relevant at grade >= 2 ("good with gaps" or better).
  Recall@k is over judged relevant jobs only; profiles with none are excluded.
- Confidence intervals: percentile bootstrap over profiles (profiles are the sampled
  unit; pairs within a profile are not independent). Comparisons between two variants
  are paired by profile: a bootstrap CI of the mean difference and a two-sided sign-flip
  permutation test.
"""

import math
import random
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from itertools import product

RELEVANT = 2


def dcg(grades: Sequence[int]) -> float:
    return sum((2.0**g - 1) / math.log2(rank + 1) for rank, g in enumerate(grades, start=1))


def ndcg_at_k(ranked: Sequence[str], grades: Mapping[str, int], k: int = 10) -> float | None:
    ideal = dcg(sorted(grades.values(), reverse=True)[:k])
    if ideal == 0:
        return None
    return dcg([grades.get(job, 0) for job in ranked[:k]]) / ideal


def reciprocal_rank(
    ranked: Sequence[str], grades: Mapping[str, int], *, min_grade: int = RELEVANT
) -> float:
    for rank, job in enumerate(ranked, start=1):
        if grades.get(job, 0) >= min_grade:
            return 1 / rank
    return 0.0


def recall_at_k(
    ranked: Sequence[str], grades: Mapping[str, int], k: int = 50, *, min_grade: int = RELEVANT
) -> float | None:
    relevant = {job for job, g in grades.items() if g >= min_grade}
    if not relevant:
        return None
    return len(relevant & set(ranked[:k])) / len(relevant)


def quantile(sorted_values: Sequence[float], q: float) -> float:
    """Linear interpolation between order statistics (numpy's default method)."""
    if not sorted_values:
        raise ValueError("no values")
    position = (len(sorted_values) - 1) * q
    low, high = math.floor(position), math.ceil(position)
    weight = position - low
    return sorted_values[low] * (1 - weight) + sorted_values[high] * weight


@dataclass(frozen=True)
class Estimate:
    mean: float
    low: float
    high: float
    n: int  # profiles

    def as_dict(self) -> dict[str, float | int]:
        return {"mean": self.mean, "ci_low": self.low, "ci_high": self.high, "n": self.n}


def bootstrap_ci(
    values: Sequence[float], *, resamples: int = 10_000, alpha: float = 0.05, seed: int = 0
) -> Estimate:
    """Mean of per-profile values and its percentile bootstrap CI."""
    if not values:
        raise ValueError("no values")
    rng = random.Random(seed)  # noqa: S311 - reproducible resampling, not security
    n = len(values)
    means = sorted(sum(rng.choices(values, k=n)) / n for _ in range(resamples))
    return Estimate(
        mean=sum(values) / n,
        low=quantile(means, alpha / 2),
        high=quantile(means, 1 - alpha / 2),
        n=n,
    )


def paired_bootstrap(
    a: Sequence[float],
    b: Sequence[float],
    *,
    resamples: int = 10_000,
    alpha: float = 0.05,
    seed: int = 0,
) -> Estimate:
    """Mean of a - b over profiles (same profile order in both) and its bootstrap CI."""
    if len(a) != len(b):
        raise ValueError("paired samples must have the same length")
    return bootstrap_ci(
        [x - y for x, y in zip(a, b, strict=True)], resamples=resamples, alpha=alpha, seed=seed
    )


def permutation_test(
    a: Sequence[float], b: Sequence[float], *, resamples: int = 10_000, seed: int = 0
) -> float:
    """Two-sided paired sign-flip test of mean(a - b) = 0. Exact (every sign pattern)
    when 2^n <= resamples, otherwise Monte Carlo with the observed pattern counted once."""
    diffs = [x - y for x, y in zip(a, b, strict=True)]
    if not diffs:
        raise ValueError("no values")
    n = len(diffs)
    observed = abs(sum(diffs)) / n
    eps = 1e-12
    if 2**n <= resamples:
        hits = sum(
            abs(sum(s * d for s, d in zip(signs, diffs, strict=True))) / n >= observed - eps
            for signs in product((1, -1), repeat=n)
        )
        return hits / float(2**n)
    rng = random.Random(seed)  # noqa: S311 - reproducible resampling, not security
    hits = 1  # the observed assignment
    for _ in range(resamples):
        flipped = sum(d if rng.random() < 0.5 else -d for d in diffs)
        hits += abs(flipped) / n >= observed - eps
    return hits / (resamples + 1)


def weighted_kappa(a: Sequence[int], b: Sequence[int], *, categories: int = 4) -> float:
    """Cohen's kappa with quadratic weights for ordinal grades 0..categories-1."""
    if len(a) != len(b) or not a:
        raise ValueError("need two equal-length, non-empty label lists")
    n = len(a)
    k = categories

    def weight(i: int, j: int) -> float:
        return ((i - j) / (k - 1)) ** 2

    observed = sum(weight(x, y) for x, y in zip(a, b, strict=True)) / n
    pa = [a.count(i) / n for i in range(k)]
    pb = [b.count(j) / n for j in range(k)]
    expected = sum(pa[i] * pb[j] * weight(i, j) for i in range(k) for j in range(k))
    if expected == 0:
        return 1.0 if observed == 0 else 0.0
    return 1 - observed / expected


@dataclass(frozen=True)
class ProfileScores:
    ndcg10: float | None
    mrr: float
    recall50: float | None


def score_profile(ranked: Sequence[str], grades: Mapping[str, int]) -> ProfileScores:
    return ProfileScores(
        ndcg10=ndcg_at_k(ranked, grades, 10),
        mrr=reciprocal_rank(ranked, grades),
        recall50=recall_at_k(ranked, grades, 50),
    )
