# ADR 0003: Two rerank profiles; the interactive setting is chosen on NDCG vs latency

- Status: accepted (interactive value interim until Phase 4)
- Date: 2026-11-23
- Decided by: project owner

## Context

The cross-encoder is by far the slowest search stage. With the plan's setting (rerank
the fused top 30 at 256 tokens per pair) it took about 1.4 s per search on this laptop,
far over the 300 ms interactive target. How much reranking is worth that time is a
ranking-quality question, and quality cannot be measured until the Phase 4 labelled set
exists.

Two uses need different trade-offs:

- **Interactive search** (`POST /api/v1/search`): someone is waiting.
- **The daily digest** ("Today" list, built offline by the worker): nobody is waiting,
  and only the top few results are shown, so quality matters most.

## Decision

Two rerank profiles in configuration (`app/core/config.py`):

| profile | used by | top (fused candidates scored) | tokens per pair |
|---|---|---:|---:|
| `digest` | the offline Today list | 30 | 256 |
| `interactive` | `POST /search` | **10 (interim)** | **128 (interim)** |

`top = 0` means no rerank. Results beyond the reranked head follow in fused order,
marked `rerank_logit: null` (a cascade), so `limit` can exceed `top`.

The final interactive value is chosen in Phase 4 from one table, measured on the same
hardware and the same labelled set:

| model and precision | setting | NDCG@10 | p50 / p95 latency (one search) | p50 / p95 at 4 and 10 in flight | CPU per search |
|---|---|---|---|---|---|
| none | no rerank | | | | |
| MiniLM-L-6 fp32 (current) | 10 @ 128 | | | | |
| MiniLM-L-6 fp32 | 20 @ 128 | | | | |
| MiniLM-L-6 fp32 | 30 @ 256 | | | | |
| MiniLM-L-6 int8 (dynamic), one pair at a time | 10 @ 128 | | | | |
| TinyBERT-L-2-v2 fp32 | 10 @ 128 | | | | |
| TinyBERT-L-2-v2 fp32 | 20 @ 128 | | | | |

Added 2026-11-24 (owner): the int8 row, because it costs 23–30% less CPU per pair than
fp32 ([measurement](../bench/rerank-variants-2026-11-23.md)) and is batch-consistent
when each pair runs alone; the TinyBERT-L-2-v2 rows (`cross-encoder/ms-marco-TinyBERT-L2-v2`),
a much smaller cross-encoder, to see how much ranking quality the latency costs. Every
candidate must pass the same build checks as the current model before it is measured
(within 0.01 logit of its PyTorch reference, and batched equal to alone). Not run yet.

The digest profile stays at 30 @ 256 unless that table shows it does not help.

## Consequences

- `POST /search` returns `rerank_profile` and `reranked`, so a client and the eval can
  see which setting produced a ranking.
- `scripts/bench_search.py` reports per-stage latency for both profiles and the four
  candidate settings; Phase 4 adds the NDCG column.
- Until Phase 4, interactive results rerank fewer candidates than planned. Jobs fused at
  rank 11 or lower are never promoted by the cross-encoder in interactive search.
