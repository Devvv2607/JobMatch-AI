# Resume claims and the evidence behind them

**Status: draft (2026-11-27).** Wording templates only. Every `{placeholder}` is filled
from one measured number in the final Phase 4 report (`eval/reports/<date>-<commit>.md`),
and each row then gets the command, the commit and the date. A claim whose number does
not support it is reworded or dropped, never rounded up.

## Rules for every claim

- It names the method exactly: **"LLM-judged"** relevance, with Gemini as the judge. Never
  "human-labelled", "human-validated", "ground truth" or "accuracy".
- It names the scale: 25 fictional profiles, one frozen snapshot of {n_jobs} jobs.
- Each number comes with its 95% CI, or a paired CI for a difference, as the report gives it.
  An improvement is claimed only if its paired CI excludes 0.
- Relative gains (percent) are computed from the reported means and labelled as relative.
- Agreement is between LLM judges only. Say so wherever kappa appears.

## Templates

| # | Claim (template) | Number(s) | Source in the report | Command | Commit / date |
|---|---|---|---|---|---|
| 1 | Built a hybrid (BM25 + vector, RRF) job search; on LLM-judged relevance (Gemini, 25 test profiles) it raised NDCG@10 from {ndcg_bm25} to {ndcg_fused} over keyword search ({diff_fused_bm25} [{ci_low}, {ci_high}], paired bootstrap over profiles). | NDCG@10 keyword, hybrid; paired diff + CI | Key results; Comparisons `query: hybrid vs keyword` | `make eval FULL=1` | {commit} / {date} |
| 2 | Added a cross-encoder reranker ({rerank_setting}); NDCG@10 {ndcg_rerank} vs {ndcg_base} without it ({diff} [{ci}]), LLM-judged (Gemini). | rerank vs +personalisation diff | Comparisons `query: +rerank … vs +personalisation` | `make eval FULL=1` | |
| 3 | Chose the interactive rerank depth by a pre-registered rule (the cheapest setting statistically tied with the best on NDCG@10): {rerank_setting} at {p95_ms} ms p95 per search. | ADR 0003 decision, p95 | ADR 0003 section; docs/bench/search-2026-11-24.md | `make eval FULL=1`, `make bench-search` | |
| 4 | Evaluated with three independent LLM judges (Gemini, Groq gpt-oss-120b, Claude); inter-judge weighted kappa {kappa_min}-{kappa_max} on 120 blind pairs, and the main conclusions {hold_summary} under each judge and their majority. | kappa range + CIs; robustness verdicts | Agreement; Robustness | `python -m app.eval.cli agreement --set eval-2026-11-25` | |
| 5 | Added a CI regression gate that re-runs search on a frozen reduced corpus with the real models and fails the build if NDCG@10 drops by more than 0.02. | gate threshold, runtime {gate_seconds} s | CI regression gate | `make eval` | |
| 6 | Completed relevance judgements to depth 10 for every compared variant ({n_pairs} LLM-judged pairs), so no variant is scored on unjudged results. | pair counts, judged@10 | Labels; Metrics (judged@10) | `make eval-fill`, `make judge` | |

## Claims we will not make

- Anything about human relevance or user satisfaction: there are no human labels.
- "Personalisation improves results": the current measurement shows
  {personalisation_diff} [{ci}] for +personalisation vs hybrid in query mode; to be
  stated as measured.
- Latency under load, or on the full snapshot: the p95 figures are single searches on
  the 2026-11-24 benchmark pool.
- Warm-start personalisation and source-quality ablations: not run (deferred).
