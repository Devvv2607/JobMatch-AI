"""The Phase 4 report (app/eval/report.py) on a small synthetic label set."""

import gzip
import json
from collections.abc import Mapping, Sequence
from pathlib import Path

from app.eval.report import build, markdown

VARIANTS = ("bm25", "vector", "fused", "rescore", "rerank_10_128", "rerank_20_128", "rerank_30_256")


def write(path: Path, rows: Sequence[Mapping[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))


def judge_rows(grades: dict[str, int], provider: str) -> list[dict[str, object]]:
    return [
        {
            "pair_id": pid,
            "label": g,
            "reason": "Right field; requires 5+ years.",
            "confidence": "high",
            "provider": provider,
            "model": provider,
            "prompt": "eval_judge/v1",
            "label_source": "llm",
        }
        for pid, g in grades.items()
    ]


def labelled_set(tmp_path: Path) -> Path:
    folder = tmp_path / "labels" / "set"
    profiles = [f"p{i:02d}" for i in range(1, 7)]
    runs, index, gemini = [], [], {}
    for p in profiles:
        for mode in ("query", "profile"):
            for v in VARIANTS:
                order = ["bad", "good"] if v == "bm25" else ["good", "bad"]
                runs.append({"profile_id": p, "variant": f"{mode}:{v}", "job_ids": order})
        for job, grade in (("good", 3), ("bad", 0)):
            pid = f"{p}:{job}"
            gemini[pid] = grade
            index.append(
                {"pair_id": pid, "profile_id": p, "job_id": job, "variants": {}, "strata": {}}
            )
    write(folder / "runs.jsonl", runs)
    write(folder / "export" / "pairs_index.jsonl", index)
    blind = [f"{p}:good" for p in profiles] + [f"{p}:bad" for p in profiles]
    (folder / "plan.json").write_text(json.dumps({"blind": blind}))
    (folder / "pool.json").write_text(
        json.dumps({"snapshot": "2026-11-25", "corpus_sha256": "ab" * 32})
    )
    corpus = tmp_path / "snapshots" / "2026-11-25" / "reduced"
    corpus.mkdir(parents=True)
    csv_rows = "\n".join(
        [
            "id,source,description_quality,posted_at",
            "good,greenhouse,full,2026-11-20 10:00:00+00",
            "bad,adzuna,snippet,2025-01-01 10:00:00+00",
        ]
    )
    (corpus / "jobs.csv.gz").write_bytes(gzip.compress(csv_rows.encode()))
    write(folder / "judge.jsonl", judge_rows(gemini, "gemini"))
    write(folder / "judge-groq-blind.jsonl", judge_rows(gemini, "groq"))
    some = dict(list(gemini.items())[:6])
    write(folder / "judge-claude-cowork.jsonl", judge_rows(some, "claude-cowork"))
    return folder


def test_report_is_llm_judged_and_marks_cowork_pending(tmp_path: Path) -> None:
    report = build(labelled_set(tmp_path), "abc1234")
    assert report["method"] == "LLM-judged (Gemini). No human relevance labels."
    assert report["pairs"]["graded"] == {"gemini": 12, "groq": 12, "cowork": 6}
    assert report["pending"].startswith("Claude Cowork on every pair")
    hybrid = report["metrics"]["unjudged0"]["comparisons"]["query: hybrid vs keyword"]
    assert hybrid["ndcg10"]["verdict"] == "better"
    assert report["rerank_choice"]["query"]["chosen"] == "rescore"  # all tie: cheapest
    row = report["robustness"]["comparisons"]["query: hybrid vs keyword"]
    assert row["groq (blind pairs)"]["vs_reference"] == "holds"
    assert "_values" not in report["metrics"]["unjudged0"]
    json.dumps(report)  # serialisable

    text = markdown(report, ["make eval FULL=1"])
    assert "LLM-judged (Gemini)" in text
    assert "human-validated" not in text.lower()
    assert "No human relevance labels" in text
    assert "**Pending:**" in text
    subsets = report["subsets"]
    assert subsets["without source snippets"]["dropped_jobs"] == 1
    assert subsets["posted within 90 days"]["dropped_jobs"] == 1
    for section in ("## Key results", "## Subsets", "## ADR 0003", "## Robustness"):
        assert section in text
