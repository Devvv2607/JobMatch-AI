# Evaluation data (Phase 4)

| Path | What | In git |
|---|---|---|
| `profiles/` | 25 fictional candidate profiles (no real person) | yes |
| `snapshots/<id>/manifest.json` | the frozen pool: dump name and hash, BM25 version, counts, exclusions, corpus fingerprint | yes |
| `snapshots/<id>/bm25/` | the frozen BM25 index | no |
| `labels/<set>/pool.json`, `runs.jsonl`, `plan.json` | how the pairs were pooled, every variant's ranking (ids only), the labelling order | yes |
| `labels/<set>/export/` | ids, grades and reasons: each LLM judge's labels | yes |
| `labels/<set>/pairs.jsonl` | the pairs with posting text: rebuilt by `python -m app.eval.cli rebuild-pairs --set <set>` | no |
| `labels/<set>/human.jsonl` | the labelling tool's event log; empty for `eval-2026-11-25` (see below) | no |
| `labels/<set>/judge*.jsonl` | LLM grades, one judge per file (exported to `export/judge_labels*.jsonl`) | no |
| `private/cowork/` | Claude Cowork's grading sheets and their manifest (`make cowork-export`) | no |
| `review/` | spot-check sheets that quote postings; verdicts go to `review-results.md` | no |

## Commands

| Command | What |
|---|---|
| `make eval` | the CI regression gate: the reduced corpus, real models, NDCG@10 of the gated query-mode variants against `gate/baseline.json` (fails on a drop > 0.02); about 1 minute |
| `make eval FULL=1` | the full report from the frozen snapshot's rankings (`runs.jsonl`) and every judge's labels: `reports/<date>-<commit>.md` and `.json` |
| `python -m app.eval.cli gate --update-baseline` | re-measure the baseline (after the labels or the corpus change, and say why in the decision log) |
| `make eval-fill SET=<set>` | add a pair for every job some variant ranked in its top 10 that has no pair yet (then `make judge`) |
| `make eval-reduce SET=<set>` | write `snapshots/<id>/reduced/` from the snapshot database |
| `python -m app.eval.cli agreement --set <set>` | judge vs judge: kappa, confusion, disagreement themes, 3-judge majority |

The reduced corpus (`snapshots/<id>/reduced/`, committed, 17 MB): every job any variant
ranked for any profile on the full snapshot (1,014 jobs) plus 3,000 distractors sampled in
proportion to source (seed 25), as Postgres COPY CSV of every column, with sha256 hashes
in `manifest.json`. Its NDCG@10 is a regression signal only; reported numbers come from
the full snapshot.

## Pairs: pooled, then every top 10 completed

The pool chose 20 pairs per profile (500) from the union of every variant's top 10, which
is 25-49 jobs per profile, so 29-39% of a variant's top 10 had no grade. Owner decision
2026-11-27: judge every variant's top 10. `make eval-fill` added the other 500 pairs
(`strata.pool = "fill-depth10"`, 1,000 in all) and Gemini judged them; the blind set and
the first 500 are unchanged.

## eval-2026-11-25 is LLM-judged only

Owner decision 2026-11-27: the set has **no human relevance labels**. The labelling tool
is retired for it (do not run `make label` on it), `human.jsonl` is empty, and the
export has no `human_labels.jsonl`. Every metric is LLM-judged and says so.

| Judge | File | Pairs | Role |
|---|---|---:|---|
| Gemini (`gemini-3.5-flash-lite`) | `judge.jsonl` | 500 | primary labels: every reported metric |
| Groq (`openai/gpt-oss-120b`) | `judge-groq-blind.jsonl` | the 120 blind pairs | agreement and robustness |
| Claude Cowork (an AI agent, provider `claude-cowork`) | `judge-claude-cowork.jsonl` | 118 so far, 500 when its batches are in | agreement and robustness |

All three grade with the same rubric (`backend/app/prompts/eval_judge/v1.md`). Gemini and
Groq receive it as the system prompt with the pair as JSON (`app/eval/judge.py`).

Claude Cowork is an LLM judge, never a human labeller, and never touches the labelling
tool. It grades in spreadsheets:

- `make cowork-export SET=eval-2026-11-25` writes `eval/private/cowork/batch-NN.xlsx`
  (gitignored): pair_id, profile, job (exactly the candidate and job objects the judge
  prompt receives), grade, reason, confidence, plus a Rubric sheet with the prompt
  verbatim. No system rank or score, retriever or other judge's label is in a sheet.
- `make cowork-import SET=eval-2026-11-25 FILE=private/cowork/batch-01.xlsx` checks each
  row (pair id in that batch, no duplicate, grade 0-3, reason at most 60 words,
  confidence high/medium/low), appends the valid ones to `judge-claude-cowork.jsonl` and
  lists every rejected row. It never writes `human.jsonl`.
- Its first 118 grades (2026-11-26) were entered through the labelling tool's card and
  have no confidence; the batches use the judge's exact input.

### History

- 2026-11-26: Claude Cowork pressed keys in the labelling tool for blind pairs 3-119 and
  one second-phase pair; those 118 events were moved out of `human.jsonl` and kept as its
  judge records (decision log, 2026-11-26; original log in
  `backups/labels-20261126T080115Z/`).
- 2026-11-27: the owner's 3 labels were moved to `human-aside.jsonl` (gitignored, never
  read): three labels are too few to report.

## Human labels, if a set ever has them

`human.jsonl` may only hold labels the owner typed in the labelling tool. No agent,
script or assistant may press keys in the tool or write to `human.jsonl`; an agent's
grades go in `judge-<agent>.jsonl` with `label_source: "llm"`. Every event records
`session_started`, so a session can be attributed or removed as a whole.

## The rubric

Every judge grades with `backend/app/prompts/eval_judge/v1.md`: 3 apply today,
2 good with gaps, 1 same field but wrong fit, 0 irrelevant. A broken dealbreaker caps
the grade at 1; per-task AI-training, rating or annotation gigs are a different kind of
work (0) even when the title names the candidate's field.
