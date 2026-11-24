# Embedder variants, 2026-11-24

[embedder_variants_experiment.py](embedder_variants_experiment.py), run in the Docker `model`
stage image on 60 real job cards (what ingest embeds; median 512 tokens, 51 of 60 at the
512 limit). 8 CPUs, mains power. Raw: [embedder-variants-2026-11-24.json](embedder-variants-2026-11-24.json).

| variant | MB | max 1-cos, sorted batches of 8 vs alone | max 1-cos, unsorted batches of 32 vs alone | min cos vs PyTorch | cards/s (8 threads) | CPU s per card (1 thread) |
|---|---:|---:|---:|---:|---:|---:|
| int8 dynamic (until 2026-11-24) | 34.1 | 0.0079 | 0.0099 | 0.9806 | 5.28 | 0.454 |
| fp32 (now) | 133.1 | 1.7e-7 | 1.7e-7 | 0.9999999 | 4.47 | 0.622 |

Threshold: max 1-cos < 0.001. int8 fails it 8x; fp32 passes.

Trial with the production embedder from the new image (200 cards, length-sorted batches of
8, read-only): 4.96 cards/s at 8 threads, 3.88 at 4 threads; peak process RSS 475 MiB.

## The re-embed (2026-11-24, `make ingest-embed`, EMBEDDING_THREADS=4)

- 11,736 current jobs re-embedded (the model variant is part of the input hash), 0 pending after.
- 2,759.6 s embedding (46.0 min, 4.25 jobs/s; projected 50 min); 2,768.8 s total; wall 2,787 s.
- Peak memory: 670 MiB process RSS; 584 MiB container cgroup `memory.peak`.
- BM25 rebuilt: 11,531 documents, 8.66 s.

Neighbour spot-check (5 jobs, exact top-5 cosine neighbours, before and after:
[before](neighbours-before-reembed-2026-11-24.txt), [after](neighbours-after-reembed-2026-11-24.txt)):
21 of 25 neighbours unchanged; one job kept its exact order; every change is a swap at
ranks 4-5 between near-ties; distances moved by 0.001-0.02.

## The ingest after it (worker catch-up, 2026-11-24 08:05-08:15 UTC)

All four sources succeeded, 0 failed boards; 551.5 s; added 239, updated 197, expired 0
(expiry needs two consecutive misses); 470 embedded; process peak RSS 885 MiB. Pool
11,531 -> 11,765.
