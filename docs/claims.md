# Resume claims and the evidence behind them

**Status: final numbers (2026-11-28), pending the owner's review.** Every number below is
measured, from the final Phase 4 report `eval/reports/2026-11-28-5c5e788.md` (made by
`make eval-final` at commit 5c5e788), or from the CI gate run that day. A claim the
numbers do not support is reworded or dropped, never rounded up.

## Rules for every claim

- It names the method exactly: **"LLM-judged"** relevance, with Gemini as the judge. Never
  "human-labelled", "human-validated", "ground truth" or "accuracy".
- It names the scale: 25 fictional profiles, one frozen snapshot of 23,705 searchable jobs.
- It names the mode: **query mode** (a typed search, as in interactive search). No claim
  is made for profile mode (the daily digest); see "Claims we will not make".
- Each number comes with its 95% CI, or a paired CI for a difference, as the report gives it.
  An improvement is claimed only if its paired CI excludes 0.
- Relative gains (percent) are computed from the reported means and labelled as relative.
- Agreement is between LLM judges only. Say so wherever kappa appears.

## Measured numbers (filled by `make eval-final`)

<!-- BEGIN:claims-numbers -->
Measured 2026-11-28T10:18:48+00:00 at commit 5c5e788 (report `eval/reports/2026-11-28-5c5e788.md`). LLM-judged (Gemini).

| Quantity | Value |
|---|---|
| keyword NDCG@10 (query) | 0.462 [0.381, 0.549] |
| hybrid NDCG@10 (query) | 0.556 [0.486, 0.631] |
| hybrid vs keyword (paired) | +0.094 [+0.047, +0.144] |
| chosen rerank `rerank_10_128` NDCG@10 | 0.575 [0.508, 0.646] |
| +personalisation vs hybrid | -0.040 [-0.100, +0.013] |
| chosen setting p95 (ms) | 331 (misses 300 ms) |
| judged@10, lowest variant | 1.00 |
| pairs (all LLM-judged) | 1000 |
| blind pairs in the final agreement (hash-identical) | 120 |
| inter-judge weighted kappa, range | 0.72-0.79 |
| kappa change after the input fix, gemini vs groq (n=120) | +0.028 [-0.051, +0.114] no clear change |
| kappa change after the input fix, gemini vs cowork (n=120) | +0.130 [+0.034, +0.230] improved |
| kappa change after the input fix, groq vs cowork (n=120) | +0.046 [-0.065, +0.156] no clear change |
<!-- END:claims-numbers -->

## Claims

All claims are query mode, LLM-judged (Gemini), 25 fictional profiles, paired bootstrap
over profiles.

| # | Claim | Number(s) | Source in the report | Command | Commit / date |
|---|---|---|---|---|---|
| 1 | **Headline (end to end).** In query mode, the full search pipeline (hybrid retrieval, personalised re-score, cross-encoder rerank 10@128) raised LLM-judged (Gemini) NDCG@10 over keyword search from 0.462 to 0.575: +0.112 [+0.053, +0.172], p=0.002 (about 24% relative). Also better without source snippets and on postings within 90 days, and under the Gemini, Groq and 3-judge-majority labels of the 120 blind pairs. | all pairs +0.112 [+0.053, +0.172] p=0.002; without snippets +0.092 [+0.029, +0.159]; within 90 days +0.072 [+0.013, +0.134]; blind pairs: Gemini +0.055 [+0.007, +0.110], Groq +0.055 [+0.009, +0.109], majority +0.048 [+0.002, +0.101]; Claude Cowork +0.056 [-0.000, +0.119] (CI touches 0: no clear difference) | Key results; Comparisons, Subsets and Robustness rows `query: +rerank 10@128 vs keyword` | `make eval-final` | 5c5e788 / 2026-11-28 |
| 2 | Supporting: in query mode, hybrid retrieval (BM25 + vector, RRF) alone raised NDCG@10 over keyword search from 0.462 to 0.556 (+0.094 [+0.047, +0.144], about 20% relative), and that holds under every judge and their majority. | +0.094 [+0.047, +0.144], p=0.001; robustness row holds in all 5 columns; without snippets +0.073 [+0.025, +0.126]; within 90 days +0.070 [+0.021, +0.124] | Comparisons, Subsets and Robustness rows `query: hybrid vs keyword` | `make eval-final` | 5c5e788 / 2026-11-28 |
| 3 | In query mode, the cross-encoder reranker (top 10, 128 tokens) raised NDCG@10 to 0.575 from 0.516 for the personalised ranking it reorders (+0.059 [+0.008, +0.114]), on all pairs. | +0.059 [+0.008, +0.114], p=0.049 | Comparisons `query: +rerank 10@128 vs +personalisation` | `make eval-final` | 5c5e788 / 2026-11-28 |
| 4 | Chose the interactive (query-mode) rerank depth by a pre-registered rule (the cheapest setting statistically tied with the best on NDCG@10): 10@128, 331 ms p95 per search, which misses the 300 ms target; faster rerankers are the next step. | eligible 10@128, 20@128, 30@256; p95 331 / 593 / 1,817 ms | ADR 0003 section; docs/bench/search-2026-11-24.md | `make eval-final`, `make bench-search` | 5c5e788 / 2026-11-28 |
| 5 | Evaluated with three LLM judges from different model families (Gemini, Groq gpt-oss-120b, Claude); inter-judge weighted kappa 0.72-0.79 on 120 blind pairs with hash-identical input. | kappa 0.725 [0.615, 0.810], 0.788 [0.704, 0.854], 0.723 [0.603, 0.813] | Agreement | `make eval-final` | 5c5e788 / 2026-11-28 |
| 6 | Found and fixed a judge-input truncation (requirements cut off in 764 of 1,000 postings): a controlled check changed 26.7% of cut pairs vs 0% of controls, so the cut pairs were re-judged; Gemini-Claude agreement rose by +0.130 kappa [+0.034, +0.230] on the same 120 pairs (the other two judge pairs: no clear change). | 8/30 vs 0/29; 143 of 764 changed; kappa change per judge pair | The input fix; Agreement, before vs after | `make eval-final` | 5c5e788 / 2026-11-28 |
| 7 | Added a CI regression gate that re-runs query-mode search on a frozen 4,014-job reduced corpus with the real models (17.5 s) and fails the build if NDCG@10 drops by more than 0.02. | threshold 0.02; 17.5 s locally, 12.8 s in CI; identical numbers on every run | CI regression gate; eval/gate/baseline.json | `make eval` | 2026-11-28 |
| 8 | Judged every compared variant's top 10 completely (1,000 LLM-judged pairs, depth-10 fill), so no variant is scored on unjudged results. | 1,000 pairs; judged@10 = 1.00 for all 14 variants | Labels; Metrics (judged@10) | `make eval-fill`, `make judge` | 5c5e788 / 2026-11-28 |

Claim 3 is weaker than claim 1: without source snippets +0.015 [-0.055, +0.088] and
within 90 days +0.032 [-0.022, +0.090] (both no clear difference), and no clear
difference under Gemini's and Groq's blind-pair labels. State it as measured on all
pairs, not as robust.

## Claims we will not make

- **"The pipeline improves profile-based daily matches."** In profile mode (no typed
  search; the daily digest) nothing is shown better than keyword search: hybrid vs keyword
  +0.002 [-0.047, +0.047], +rerank 10@128 vs keyword +0.021 [-0.033, +0.072], and the
  digest's 30@256 vs no rerank +0.002 [-0.054, +0.055], all no clear difference
  (NDCG@10, Gemini, all pairs). Groq's and Cowork's blind-pair labels find +rerank 10@128
  vs keyword better in profile mode (+0.041 [+0.002, +0.088], +0.039 [+0.001, +0.089]);
  Gemini's and the majority's do not. Backlogged as Phase 5 B0.
- **"Personalisation improves results."** In query mode it does not: +personalisation vs
  hybrid is NDCG@10 -0.040 [-0.100, +0.013] (no clear difference) and **MRR -0.159
  [-0.304, -0.008], worse** (the first relevant job comes later; permutation p = 0.051).
  On postings without snippets NDCG@10 is +0.004 [-0.072, +0.075] and within 90 days
  -0.030 [-0.094, +0.029] (no clear difference). Under Cowork's and the majority's
  blind-pair labels NDCG@10 is worse (-0.058 [-0.109, -0.013]; -0.044 [-0.094, -0.000]).
  In profile mode +0.041 [-0.018, +0.100], no clear difference.
- Anything about human relevance or user satisfaction: there are no human labels.
- "The end-to-end gain holds under every judge": under Claude Cowork's blind-pair labels
  it is +0.056 [-0.000, +0.119], a CI that touches 0.
- "The reranker beats hybrid search": +rerank 10@128 is better than the personalised
  ranking it reorders, but not shown better than plain hybrid (0.575 vs 0.556, not
  tested as a pair in the report).
- "Vector search beats keyword" as a robust claim: +0.085 [+0.012, +0.164] under Gemini
  on all pairs, but no clear difference under every blind-pair judge.
- "Meets a 300 ms latency target": the chosen setting is 331 ms p95.
- Latency under load, or on the full snapshot: the p95 figures are single searches on
  the 2026-11-24 benchmark pool.
- Warm-start personalisation and source-quality ablations: not run (deferred).
