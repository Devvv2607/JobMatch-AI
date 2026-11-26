# Evaluation data (Phase 4)

| Path | What | In git |
|---|---|---|
| `profiles/` | 25 fictional candidate profiles (no real person) | yes |
| `snapshots/<id>/manifest.json` | the frozen pool: dump name and hash, BM25 version, counts, exclusions, corpus fingerprint | yes |
| `snapshots/<id>/bm25/` | the frozen BM25 index | no |
| `labels/<set>/pool.json`, `runs.jsonl`, `plan.json` | how the pairs were pooled, every variant's ranking (ids only), the labelling order | yes |
| `labels/<set>/export/` | ids, grades and reasons: human labels, each judge's labels | yes |
| `labels/<set>/pairs.jsonl` | the pairs with posting text: rebuilt by `python -m app.eval.cli rebuild-pairs --set <set>` | no |
| `labels/<set>/human.jsonl` | the labelling tool's event log (exported to `export/human_labels.jsonl`) | no |
| `labels/<set>/judge*.jsonl` | machine grades, one model per file (exported to `export/judge_labels*.jsonl`) | no |
| `review/` | spot-check sheets that quote postings; verdicts go to `review-results.md` | no |

## Human labels must be entered by a human

`human.jsonl` is the human ground truth: every label in it must be typed by the owner in
the labelling tool (`make label SET=<set>`). No agent, script or assistant may press keys
in the tool or write to `human.jsonl`.

- Grades from an AI agent go in their own file, `labels/<set>/judge-<agent>.jsonl`, with
  `provider` set to the agent and `label_source: "llm"`. They are compared with the
  human and judge labels; they never count as human labels.
- Every event in `human.jsonl` records `session_started`: when that run of the labelling
  tool began. Labels from one session share it, so a session can be attributed or
  removed as a whole.
- 2026-11-26: Claude Cowork (an AI agent) graded blind pairs 3-120 and pressed keys in
  the tool. Those labels were moved to `judge-claude-cowork.jsonl` (with its own sheet of
  reasons) and `human.jsonl` was cut back to the owner's labels; the original log is in
  `backups/labels-20261126T080115Z/` (decision log, 2026-11-26).

## The rubric

The human labeller and the LLM judge grade with the same rubric
(`backend/app/prompts/eval_judge/v1.md`, shown in the tool with R): 3 apply today,
2 good with gaps, 1 same field but wrong fit, 0 irrelevant. A broken dealbreaker caps
the grade at 1; per-task AI-training, rating or annotation gigs are a different kind of
work (0) even when the title names the candidate's field.
