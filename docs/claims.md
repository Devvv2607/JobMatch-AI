# Resume claims and the evidence behind them

**Status: final numbers (2026-11-28), pending the owner's review.** Every number below is
measured, from the final Phase 4 report `eval/reports/2026-11-28-65efa6a.md` (made by
`make eval-final` at commit 65efa6a), or from the CI gate run that day. A claim the
numbers do not support is reworded or dropped, never rounded up.

## Rules for every claim

- It names the method exactly: **"LLM-judged"** relevance, with Gemini as the judge. Never
  "human-labelled", "human-validated", "ground truth" or "accuracy".
- It names the scale: 25 fictional profiles, one frozen snapshot of 23,705 searchable jobs.
- Each number comes with its 95% CI, or a paired CI for a difference, as the report gives it.
  An improvement is claimed only if its paired CI excludes 0.
- Relative gains (percent) are computed from the reported means and labelled as relative.
- Agreement is between LLM judges only. Say so wherever kappa appears.

## Measured numbers (filled by `make eval-final`)

<!-- BEGIN:claims-numbers -->
Measured 2026-11-28T10:00:28+00:00 at commit 65efa6a (report `eval/reports/2026-11-28-65efa6a.md`). LLM-judged (Gemini).

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

| # | Claim | Number(s) | Source in the report | Command | Commit / date |
|---|---|---|---|---|---|
| 1 | Built a hybrid (BM25 + vector, RRF) job search; on LLM-judged relevance (Gemini, 25 fictional test profiles) it raised NDCG@10 from 0.462 to 0.556 over keyword search (+0.094 [+0.047, +0.144], paired bootstrap over profiles; about 20% relative). | 0.462 [0.381, 0.549]; 0.556 [0.486, 0.631]; +0.094 [+0.047, +0.144], p=0.001 | Key results; Comparisons `query: hybrid vs keyword` | `make eval-final` | 65efa6a / 2026-11-28 |
| 2 | Added a cross-encoder reranker (top 10, 128 tokens) to interactive search: NDCG@10 0.575 vs 0.516 for the personalised ranking it reorders (+0.059 [+0.008, +0.114]), LLM-judged (Gemini). | +0.059 [+0.008, +0.114], p=0.049 | Comparisons `query: +rerank 10@128 vs +personalisation` | `make eval-final` | 65efa6a / 2026-11-28 |
| 3 | Chose the interactive rerank depth by a pre-registered rule (the cheapest setting statistically tied with the best on NDCG@10): 10@128, 331 ms p95 per search, which misses the 300 ms target; faster rerankers are the next step. | eligible 10@128, 20@128, 30@256; p95 331 / 593 / 1,817 ms | ADR 0003 section; docs/bench/search-2026-11-24.md | `make eval-final`, `make bench-search` | 65efa6a / 2026-11-28 |
| 4 | Evaluated with three LLM judges from different model families (Gemini, Groq gpt-oss-120b, Claude); inter-judge weighted kappa 0.72-0.79 on 120 blind pairs with hash-identical input. Hybrid beats keyword under every judge and their majority. | kappa 0.725 [0.615, 0.810], 0.788 [0.704, 0.854], 0.723 [0.603, 0.813]; robustness row `query: hybrid vs keyword` holds in all 5 columns | Agreement; Robustness | `make eval-final` | 65efa6a / 2026-11-28 |
| 5 | Found and fixed a judge-input truncation (requirements cut off in 764 of 1,000 postings): a controlled check changed 26.7% of cut pairs vs 0% of controls, so the cut pairs were re-judged; Gemini-Claude agreement rose by +0.130 kappa [+0.034, +0.230] on the same 120 pairs. | 8/30 vs 0/29; 143 of 764 changed; kappa change per judge pair | The input fix; Agreement, before vs after | `make eval-final` | 65efa6a / 2026-11-28 |
| 6 | Added a CI regression gate that re-runs search on a frozen 4,014-job reduced corpus with the real models (17.5 s) and fails the build if NDCG@10 drops by more than 0.02. | threshold 0.02; 17.5 s; identical on two runs | CI regression gate; eval/gate/baseline.json | `make eval` | 2026-11-28 |
| 7 | Judged every compared variant's top 10 completely (1,000 LLM-judged pairs, depth-10 fill), so no variant is scored on unjudged results. | 1,000 pairs; judged@10 = 1.00 for all 14 variants | Labels; Metrics (judged@10) | `make eval-fill`, `make judge` | 65efa6a / 2026-11-28 |

Claim 2 is weaker on the subsets: without source snippets +0.015 [-0.055, +0.088], and
within 90 days +0.032 [-0.022, +0.090], both no clear difference. Under Gemini's and
Groq's blind-pair labels it is also no clear difference (Robustness). State it as
measured on all pairs, not as robust.

## Claims we will not make

- Anything about human relevance or user satisfaction: there are no human labels.
- "Personalisation improves results": +personalisation vs hybrid is -0.040
  [-0.100, +0.013] in query mode (no clear difference) and +0.041 [-0.018, +0.100] in
  profile mode (no clear difference).
- "The reranker beats hybrid search": +rerank 10@128 is better than the personalised
  ranking it reorders, but not shown better than plain hybrid (0.575 vs 0.556, not
  tested as a pair in the report).
- "Vector search beats keyword" as a robust claim: +0.085 [+0.012, +0.164] under Gemini
  on all pairs, but no clear difference under every blind-pair judge.
- "Meets a 300 ms latency target": the chosen setting is 331 ms p95.
- Latency under load, or on the full snapshot: the p95 figures are single searches on
  the 2026-11-24 benchmark pool.
- Warm-start personalisation and source-quality ablations: not run (deferred).
