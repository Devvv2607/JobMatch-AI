# ADR 0003: Two rerank profiles; the interactive setting is chosen on NDCG vs latency

- Status: accepted 2026-11-23 (interactive value interim); Phase 4 decision pending the
  final labels (filled below by `make eval-final`)
- Date: 2026-11-23; Phase 4 update 2026-11-27
- Decided by: project owner

## Context

The cross-encoder is by far the slowest search stage. With the plan's setting (rerank
the fused top 30 at 256 tokens per pair) it took about 1.4 s per search on this laptop,
far over the 300 ms interactive target. How much reranking is worth that time is a
ranking-quality question, and quality could not be measured until Phase 4.

Two uses need different trade-offs:

- **Interactive search** (`POST /api/v1/search`): someone is waiting.
- **The daily digest** ("Today" list, built offline by the worker): nobody is waiting,
  and only the top few results are shown, so quality matters most.

## Decision (2026-11-23)

Two rerank profiles in configuration (`app/core/config.py`):

| profile | used by | top (fused candidates scored) | tokens per pair |
|---|---|---:|---:|
| `digest` | the offline Today list | 30 | 256 |
| `interactive` | `POST /search` | **10 (interim)** | **128 (interim)** |

`top = 0` means no rerank. Results beyond the reranked head follow in fused order,
marked `rerank_logit: null` (a cascade), so `limit` can exceed `top`.

## Phase 4: how the interactive value is chosen

### Options measured

Four settings, all on the same frozen snapshot, profiles and labels (eval/report.md):

| option | setting | single-search latency p50 / p95 (ms)* |
|---|---|---|
| A | no rerank (personalised re-score only) | 62 / 75 |
| B | MiniLM-L-6, top 10 @ 128 tokens (the interim value) | 292 / 331 |
| C | MiniLM-L-6, top 20 @ 128 | 506 / 593 |
| D | MiniLM-L-6, top 30 @ 256 (the digest value) | 1,588 / 1,817 |

\* `docs/bench/search-2026-11-24.md`, "Phase 4 candidates": one search at a time, real
models, 11,531-job pool, the owner's laptop.

The int8 MiniLM and TinyBERT-L-2-v2 rows (added 2026-11-24) were **not measured**: the
models were not built, and the owner deferred them on 2026-11-27. They remain the
first candidates if the chosen setting misses the latency target.

### Quality measure

NDCG@10 in query mode (what interactive search runs), LLM-judged (Gemini), mean over the
25 profiles, with a 95% bootstrap CI over profiles. Every variant's top 10 is fully
judged (depth-10 fill), so no assumption about unjudged jobs enters it.

### Decision rule (paired form, owner decision 2026-11-27)

1. Find the setting with the best mean NDCG@10.
2. A setting is **eligible** if its mean is within 0.01 of the best, or if the paired
   bootstrap CI (over profiles) of its difference to the best includes 0. In other words,
   it's not measurably worse than the best.
3. Among the eligible settings, choose the one with the **lowest single-search p95**.
4. State whether the choice meets the **300 ms** p95 target.
5. Check that the choice holds under the other judges (Groq, Claude Cowork, the majority;
   eval/report.md section 7) and under the v2 labels (sensitivity). If not, say so.

Why paired: the first wording ("CI overlaps the best's CI") compared each setting's own
CI. With 25 profiles those always overlap, so the rule would always pick no rerank, even
when every profile ranks better with reranking. Comparing the same profiles under two
settings removes the profile-to-profile variation that makes those CIs wide.

### The digest

The digest keeps 30 @ 256 unless the measurements show it does not help: profile mode,
30@256 vs no rerank. Latency is irrelevant there.

## Phase 4 result

<!-- BEGIN:adr -->
_Pending: filled by `make eval-final` from the final labels (NDCG@10 per setting, the
paired differences, the eligible set, the choice, its p95, the 300 ms verdict and the
robustness check)._
<!-- END:adr -->

## Consequences

- `POST /search` returns `rerank_profile` and `reranked`, so a client and the eval can
  see which setting produced a ranking.
- If the chosen setting differs from the interim 10@128, `rerank_interactive_top` /
  `rerank_interactive_tokens` change in `app/core/config.py`, with the CI regression gate
  re-baselined in the same change.
- If the choice misses 300 ms, the int8 and TinyBERT options are measured next.
- Jobs fused at rank 11 or lower are never promoted by the cross-encoder in interactive
  search while the setting is 10@N.
