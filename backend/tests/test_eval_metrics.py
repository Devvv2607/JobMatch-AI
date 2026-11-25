"""Eval metrics against toy examples computed by hand (app/eval/metrics.py).

Worked example used below: a variant ranks [a, b, c]; judged grades a=3, b=0, c=2, d=1
(d was judged but not retrieved).
  DCG@3  = (2^3-1)/log2(2) + (2^0-1)/log2(3) + (2^2-1)/log2(4) = 7 + 0 + 1.5 = 8.5
  IDCG@3 = grades sorted [3, 2, 1]: 7 + 3/log2(3) + 1/log2(4) = 7 + 1.8927893 + 0.5
         = 9.3927893
  NDCG@3 = 8.5 / 9.3927893 = 0.9049495
"""

import math

import pytest

from app.eval.metrics import (
    bootstrap_ci,
    dcg,
    ndcg_at_k,
    paired_bootstrap,
    permutation_test,
    quantile,
    recall_at_k,
    reciprocal_rank,
    score_profile,
    weighted_kappa,
)

GRADES = {"a": 3, "b": 0, "c": 2, "d": 1}
RANKED = ["a", "b", "c"]


def test_dcg_by_hand() -> None:
    assert dcg([3, 0, 2]) == pytest.approx(8.5)
    assert dcg([]) == 0


def test_ndcg_by_hand() -> None:
    assert ndcg_at_k(RANKED, GRADES, 3) == pytest.approx(0.9049495, abs=1e-7)
    # @2: DCG = 7; IDCG = 7 + 3/log2(3) = 8.8927893 -> 0.7871546
    assert ndcg_at_k(RANKED, GRADES, 2) == pytest.approx(0.7871546, abs=1e-7)
    # A perfect order scores 1; unjudged retrieved jobs count as 0.
    assert ndcg_at_k(["a", "c", "d"], GRADES, 3) == pytest.approx(1.0)
    assert ndcg_at_k(["x", "a"], {"a": 3}, 2) == pytest.approx(1 / math.log2(3))


def test_ndcg_is_undefined_without_a_relevant_judged_job() -> None:
    assert ndcg_at_k(["a"], {"a": 0, "b": 0}, 10) is None


def test_reciprocal_rank_uses_grade_2_or_more() -> None:
    assert reciprocal_rank(["d", "b", "c"], GRADES) == pytest.approx(1 / 3)  # d=1 is not enough
    assert reciprocal_rank(["a"], GRADES) == 1.0
    assert reciprocal_rank(["b", "d"], GRADES) == 0.0


def test_recall_over_judged_relevant_jobs() -> None:
    grades = {"a": 3, "c": 2, "e": 2, "b": 1}  # relevant: a, c, e
    assert recall_at_k(["a", "b", "c"], grades, 2) == pytest.approx(1 / 3)
    assert recall_at_k(["a", "b", "c"], grades, 3) == pytest.approx(2 / 3)
    assert recall_at_k(["a"], {"a": 1}, 50) is None


def test_score_profile_bundles_the_three() -> None:
    s = score_profile(RANKED, GRADES)
    assert s.ndcg10 == pytest.approx(8.5 / (7 + 3 / math.log2(3) + 0.5))
    assert s.mrr == 1.0
    assert s.recall50 == 1.0  # a and c are the relevant ones, both retrieved


def test_quantile_interpolates_like_numpy() -> None:
    values = [1.0, 2.0, 3.0, 4.0]
    assert quantile(values, 0.0) == 1.0
    assert quantile(values, 1.0) == 4.0
    assert quantile(values, 0.5) == 2.5  # position 1.5
    assert quantile(values, 0.25) == pytest.approx(1.75)  # position 0.75


def test_bootstrap_of_constant_values_has_a_zero_width_interval() -> None:
    est = bootstrap_ci([0.6] * 25, resamples=500)
    assert est.mean == pytest.approx(0.6)
    assert est.low == pytest.approx(0.6)
    assert est.high == pytest.approx(0.6)
    assert est.n == 25


def test_bootstrap_interval_contains_the_mean_and_is_reproducible() -> None:
    values = [0.2, 0.4, 0.5, 0.9, 0.7, 0.3, 0.8, 0.6]
    first = bootstrap_ci(values, resamples=2000, seed=7)
    assert first.low < first.mean < first.high
    assert first == bootstrap_ci(values, resamples=2000, seed=7)


def test_paired_bootstrap_is_the_bootstrap_of_differences() -> None:
    a, b = [0.5, 0.7, 0.9], [0.4, 0.5, 0.6]
    est = paired_bootstrap(a, b, resamples=1000, seed=3)
    assert est.mean == pytest.approx(0.2)  # (0.1 + 0.2 + 0.3) / 3
    diffs = [x - y for x, y in zip(a, b, strict=True)]
    assert est == bootstrap_ci(diffs, resamples=1000, seed=3)
    assert 0.1 - 1e-9 <= est.low <= est.high <= 0.3 + 1e-9
    with pytest.raises(ValueError):
        paired_bootstrap([0.1], [0.1, 0.2])


def test_exact_permutation_test_by_hand() -> None:
    # Differences [1, 1, 1]: of the 8 sign patterns only +++ and --- reach |mean| >= 1.
    assert permutation_test([2.0, 2.0, 2.0], [1.0, 1.0, 1.0]) == pytest.approx(2 / 8)
    # Differences [1, -1]: every pattern has |mean| 0 or 1; observed 0 -> p = 1.
    assert permutation_test([1.0, 0.0], [0.0, 1.0]) == 1.0
    # [2, 1]: patterns ++ (1.5), +- (0.5), -+ (0.5), -- (1.5); observed 1.5 -> 2/4.
    assert permutation_test([2.0, 1.0], [0.0, 0.0]) == pytest.approx(0.5)


def test_monte_carlo_permutation_test_on_a_clear_difference() -> None:
    a = [0.8] * 20
    b = [0.2] * 20  # 2^20 patterns > 2000 resamples: Monte Carlo
    p = permutation_test(a, b, resamples=2000, seed=1)
    assert 0 < p < 0.01  # only all-plus / all-minus match; the observed counts once


def test_weighted_kappa_by_hand() -> None:
    assert weighted_kappa([0, 1, 2, 3], [0, 1, 2, 3]) == pytest.approx(1.0)
    # Two categories reduce to Cohen's kappa: po = 0.75, pe = 0.5*0.25 + 0.5*0.75 = 0.5
    # -> (0.75 - 0.5) / (1 - 0.5) = 0.5.
    assert weighted_kappa([0, 0, 1, 1], [0, 1, 1, 1], categories=2) == pytest.approx(0.5)
    # Opposite extremes: observed weighted disagreement 1, expected 0.5 -> 1 - 1/0.5 = -1.
    assert weighted_kappa([0, 3], [3, 0]) == pytest.approx(-1.0)
    # Off by one on a 0-3 scale costs (1/3)^2 = 1/9 of a full disagreement:
    # a = [0, 1, 2, 3], b = [1, 1, 2, 3]: observed = (1/9)/4 = 1/36;
    # pa = 1/4 each; pb = [0, 1/2, 1/4, 1/4];
    # expected = sum_i sum_j pa_i pb_j (i-j)^2/9 = (1/4)(1/9) * sum_i [ (1/2)(i-1)^2 +
    #   (1/4)(i-2)^2 + (1/4)(i-3)^2 ] = (1/36) * (3 + 3/2 + 7/2) = 8/36
    # -> kappa = 1 - (1/36)/(8/36) = 7/8.
    assert weighted_kappa([0, 1, 2, 3], [1, 1, 2, 3]) == pytest.approx(7 / 8)
