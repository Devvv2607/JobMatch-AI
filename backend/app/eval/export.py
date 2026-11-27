"""What of a label set is committed, and how the rest is rebuilt (owner decision
2026-11-26).

Committed, under eval/labels/<set>/export/ (no posting text):
- pairs_index.jsonl: pair_id, profile_id, job_id, the variants that surfaced the job
  (variant -> rank) and its strata;
- human_labels.jsonl, only when the set has human labels: the owner's current label per
  pair: pair_id, grade, label_source (human_blind / human_with_suggestion /
  human_no_suggestion), labelled_at. Owner decision 2026-11-27: eval-2026-11-25 is
  LLM-judged only (no human labels), so it has none and a stale file is removed;
- judge_labels<suffix>.jsonl, one per judge file: pair_id, grade, reason, confidence,
  provider, model, prompt (version), prompt_tokens, completion_tokens, cached.
Plus plan.json, pool.json and runs.jsonl (ids and counts only).

Not committed: pairs.jsonl (it quotes each posting). It is rebuilt exactly from
pairs_index.jsonl and the snapshot database named in pool.json:
`python -m app.eval.cli rebuild-pairs --set <set>` (each job card comes from the
snapshot's frozen row through app/eval/cards.py, as when it was pooled).
"""

import json
from pathlib import Path
from typing import Any

from app.eval.labels import Event, LabelState
from app.eval.pairs import EvalPair, JudgeRecord, read_jsonl

EXPORT_DIR = "export"


def _write(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def pairs_index(pairs: list[EvalPair]) -> list[dict[str, Any]]:
    return [
        {
            "pair_id": p.pair_id,
            "profile_id": p.profile_id,
            "job_id": p.job.job_id,
            "variants": p.variants,
            "strata": p.strata,
        }
        for p in pairs
    ]


def human_labels(log: Path) -> list[dict[str, Any]]:
    state = LabelState()
    for raw in read_jsonl(log):
        state.apply(Event.model_validate(raw))
    return [
        {
            "pair_id": pid,
            "grade": entry.label,
            "label_source": entry.source,
            "labelled_at": entry.at,
        }
        for pid, entry in sorted(state.labelled().items())
    ]


def judge_labels(path: Path) -> list[dict[str, Any]]:
    """The latest record per pair, in pair order."""
    latest = {r.pair_id: r for r in (JudgeRecord.model_validate(x) for x in read_jsonl(path))}
    fields = (
        "pair_id",
        "label",
        "reason",
        "confidence",
        "provider",
        "model",
        "prompt",
        "prompt_tokens",
        "completion_tokens",
        "cached",
        "label_source",
    )
    rows = []
    for pid in sorted(latest):
        data = latest[pid].model_dump()
        row = {k: data[k] for k in fields}
        row["grade"] = row.pop("label")
        rows.append(row)
    return rows


def export_set(folder: Path, pairs: list[EvalPair]) -> dict[str, int]:
    """Writes the committed files; returns row counts per file."""
    out = folder / EXPORT_DIR
    counts: dict[str, int] = {}
    files: dict[str, list[dict[str, Any]]] = {"pairs_index.jsonl": pairs_index(pairs)}
    if humans := human_labels(folder / "human.jsonl"):
        files["human_labels.jsonl"] = humans
    else:
        (out / "human_labels.jsonl").unlink(missing_ok=True)
    for judge_file in sorted(folder.glob("judge*.jsonl")):
        if "aside" in judge_file.name or "sample" in judge_file.name:
            continue  # kept aside on purpose (mixed providers / an earlier input)
        files[judge_file.name.replace("judge", "judge_labels", 1)] = judge_labels(judge_file)
    for name, rows in files.items():
        _write(out / name, rows)
        counts[name] = len(rows)
    return counts
