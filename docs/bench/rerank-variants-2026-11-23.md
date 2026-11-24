# Reranker variants, 2026-11-23

Script: [rerank_variants_experiment.py](rerank_variants_experiment.py), run in the Docker `model` stage image
(torch + onnxruntime.quantization). 150 real job passages for testing, 150 others for static
calibration; 10 queries x 30 passages; 8 CPUs, onnxruntime default threads. "single" = one pair per
run; "batch" = all pairs padded together; "sorted" = length-sorted batches of 8. Raw numbers:
[rerank-variants-2026-11-23.json](rerank-variants-2026-11-23.json).

| variant | MB | max abs(d) batch vs single, 128 / 256 tok | max abs(d) sorted-8 vs single, 128 / 256 | Pearson vs torch fp32 (min), 128 / 256 | top-10 overlap vs torch, 128 / 256 | ms 10@128 single / batch / sorted | ms 30@256 single / batch / sorted |
|---|---:|---|---|---|---|---|---|
| fp32 | 91.0 | 0.0 / 0.0 | 0.0 / 0.0 | 1.0 / 1.0 | 1.0 / 1.0 | 344.0 / 161.1 / 162.9 | 1178.1 / 1383.0 / 1148.7 |
| int8 dynamic (current) | 23.2 | 0.4586 / 0.4362 | 0.4871 / 0.4477 | 0.9938 / 0.9952 | 0.97 / 0.93 | 198.4 / 275.9 / 391.1 | 1091.9 / 1330.2 / 1233.9 |
| int8 static MinMax per-channel | 23.3 | 0.0 / 0.5674 | 0.0 / 0.5674 | 0.9693 / 0.963 | 0.94 / 0.92 | 165.9 / 117.1 / 119.5 | 1068.0 / 1327.4 / 771.0 |
| int8 static MinMax per-tensor | 23.1 | 0.0 / 1.1916 | 0.0 / 1.1916 | 0.9584 / 0.9479 | 0.9 / 0.91 | 167.8 / 122.2 / 122.4 | 1211.9 / 1235.0 / 801.0 |

Static int8 shows 0.0 at 128 tokens only because every passage filled 128 tokens (no padding);
at 256 tokens padded batches diverge. Percentile calibration was killed for memory in the 6 GB VM.

CPU per pair, one thread, 60 passages (2026-11-24, same image):

| tokens | fp32 sorted batches of 8 | int8 dynamic one at a time |
|---:|---:|---:|
| 128 | 53.6 ms | 41.3 ms |
| 256 | 129.1 ms | 90.9 ms |
