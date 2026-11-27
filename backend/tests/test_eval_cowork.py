"""Claude Cowork grading sheets (app/eval/cowork.py): export and checked import."""

import json
from pathlib import Path

import pytest
from openpyxl import load_workbook

from app.eval.cowork import (
    JUDGE_FILE,
    RUBRIC_SHEET,
    SHEET,
    export_batches,
    import_sheet,
    plan_batches,
    sheet_cells,
)
from app.eval.judge import pair_input
from app.eval.pairs import EvalPair, JobCard, load_judge, pair_id
from app.eval.profiles import load_profiles

PROFILES = load_profiles()
RUBRIC = "Rubric (one grade, 0 to 3):\n- 3 = apply today."


def pair(i: int, profile: str = "p02") -> EvalPair:
    job = JobCard(
        job_id=f"j{i}",
        title="NLP Engineer",
        company="Acme",
        source="greenhouse",
        location="Bengaluru, India",
        eligibility="IN",
        workplace="hybrid",
        employment="full_time",
        poster="employer",
        description=f"Build NLP model {i} in PyTorch.",
    )
    return EvalPair(
        pair_id=pair_id(profile, job.job_id),
        profile_id=profile,
        job=job,
        variants={"bm25": 1, "vector_rerank": 3},
        strata={"source": "greenhouse"},
    )


PAIRS = [pair(i) for i in range(12)]
BLIND = [p.pair_id for p in PAIRS[:4]]


def test_batches_put_ungraded_blind_first_then_split_the_rest_evenly() -> None:
    graded = {BLIND[3], PAIRS[5].pair_id}
    batches = plan_batches(PAIRS, BLIND, graded, per_batch=3)
    assert batches[0] == BLIND[:3]
    rest = [pid for b in batches[1:] for pid in b]
    assert sorted(rest) == sorted(p.pair_id for p in PAIRS[4:] if p.pair_id not in graded)
    assert [len(b) for b in batches[1:]] == [4, 3]  # about per_batch each
    assert plan_batches(PAIRS, BLIND, graded, per_batch=3) == batches  # seeded


def test_sheet_cells_are_exactly_the_judge_input_and_leak_no_ranks() -> None:
    candidate, job = sheet_cells(PROFILES["p02"], PAIRS[0])
    body = json.loads(pair_input(PROFILES["p02"], PAIRS[0]).removeprefix("<pair>")[:-7])
    assert json.loads(candidate) == body["candidate"]
    assert json.loads(job) == body["job"]
    for leak in ("bm25", "vector_rerank", "variants", "strata", "greenhouse"):
        assert leak not in job


def export(tmp_path: Path) -> tuple[Path, dict[str, list[str]]]:
    out = tmp_path / "cowork"
    names = export_batches(out, PAIRS, PROFILES, BLIND, set(), RUBRIC, per_batch=4)
    return out, names


def test_export_writes_sheets_rubric_and_manifest_and_never_overwrites(tmp_path: Path) -> None:
    out, names = export(tmp_path)
    assert list(names) == ["batch-00", "batch-01", "batch-02"]
    wb = load_workbook(out / "batch-01.xlsx")
    rows = list(wb[SHEET].iter_rows(values_only=True))
    assert rows[0] == ("pair_id", "profile", "job", "grade", "reason", "confidence")
    assert [r[0] for r in rows[1:]] == names["batch-01"]
    assert all(r[3:] == (None, None, None) for r in rows[1:])
    assert [r[0] for r in wb[RUBRIC_SHEET].iter_rows(values_only=True)] == RUBRIC.splitlines()
    manifest = json.loads((out / "manifest.json").read_text())
    assert manifest["batches"] == names
    with pytest.raises(FileExistsError):
        export(tmp_path)


def fill(
    path: Path,
    values: dict[str, tuple[int | str, str, str]],
    extra: list[tuple[int | str, ...]] | None = None,
) -> None:
    wb = load_workbook(path)
    ws = wb[SHEET]
    for row in ws.iter_rows(min_row=2):
        filled = values.get(str(row[0].value))
        if filled is not None:
            row[3].value, row[4].value, row[5].value = filled
    for line in extra or []:
        ws.append(list(line))
    wb.save(path)


def test_import_checks_every_row_and_appends_only_the_valid_ones(tmp_path: Path) -> None:
    out, names = export(tmp_path)
    ids = names["batch-01"]
    folder = tmp_path / "set"
    folder.mkdir()
    (folder / "human.jsonl").write_text("")
    fill(
        out / "batch-01.xlsx",
        {
            ids[0]: (2, "Right field, Bengaluru hybrid; misses Spark.", "High "),
            ids[1]: ("4", "Too high.", "high"),
            ids[2]: (1, " ".join(["word"] * 61), "sure"),
        },
        extra=[
            (ids[0], "", "", 3, "A duplicate row.", "low"),
            (names["batch-02"][0], "", "", 1, "Pair from another batch.", "low"),
        ],
    )
    report = import_sheet(out / "batch-01.xlsx", folder, out / "manifest.json")
    assert [r.pair_id for r in report.accepted] == [ids[0]]
    assert report.accepted[0].confidence == "high"
    assert report.distribution() == {0: 0, 1: 0, 2: 1, 3: 0}
    reasons = {pid: why for _, pid, why in report.rejected}
    assert "not 0-3" in reasons[ids[1]]
    assert "61 words" in reasons[ids[2]] and "confidence" in reasons[ids[2]]
    assert any("duplicate" in why for _, _, why in report.rejected)
    assert "not in batch-01" in reasons[names["batch-02"][0]]
    assert report.ungraded == [ids[3]]

    saved = load_judge(folder / JUDGE_FILE)
    assert list(saved) == [ids[0]]
    assert saved[ids[0]].provider == "claude-cowork"
    assert saved[ids[0]].label_source == "llm"
    assert (folder / "human.jsonl").read_text() == ""  # never written

    again = import_sheet(out / "batch-01.xlsx", folder, out / "manifest.json")
    assert again.accepted == [] and again.already == 1
    assert len(load_judge(folder / JUDGE_FILE)) == 1


def test_import_needs_a_batch_name(tmp_path: Path) -> None:
    out, _ = export(tmp_path)
    renamed = out / "grades.xlsx"
    (out / "batch-01.xlsx").rename(renamed)
    with pytest.raises(ValueError, match="batch-NN"):
        import_sheet(renamed, tmp_path, out / "manifest.json")


def test_import_refuses_an_ungraded_sheet(tmp_path: Path) -> None:
    out, _ = export(tmp_path)
    with pytest.raises(ValueError, match="no grades yet"):
        import_sheet(out / "batch-01.xlsx", tmp_path, out / "manifest.json")


def test_a_v3_batch_writes_its_own_file_and_keeps_the_earlier_grade(tmp_path: Path) -> None:
    from app.eval.cowork import export_named_batch

    out, names = export(tmp_path)
    folder = tmp_path / "set"
    folder.mkdir()
    pid = names["batch-00"][0]
    # The same pair was graded earlier on v2 (batch-00) ...
    fill(out / "batch-00.xlsx", {pid: (2, "Good fit, salary not stated.", "medium")})
    import_sheet(out / "batch-00.xlsx", folder, out / "manifest.json")
    # ... and again on v3 in its own batch, into its own file.
    export_named_batch(
        out,
        "batch-05",
        [pid],
        PAIRS,
        PROFILES,
        RUBRIC,
        input_version=3,
        judge_file="judge-claude-cowork-v3.jsonl",
    )
    fill(out / "batch-05.xlsx", {pid: (1, "Requires 5+ years; candidate has 2.", "high")})
    report = import_sheet(out / "batch-05.xlsx", folder, out / "manifest.json", {pid: {3: "abc"}})
    assert [r.label for r in report.accepted] == [1] and not report.rejected
    v3 = load_judge(folder / "judge-claude-cowork-v3.jsonl")[pid]
    assert (v3.label, v3.input_sha256) == (1, "abc")
    assert "+input3; sheet batch-05" in v3.prompt
    assert load_judge(folder / JUDGE_FILE)[pid].label == 2  # history kept


def test_load_judge_refuses_a_file_from_newer_code(tmp_path: Path) -> None:
    from app.eval.pairs import StaleCodeError

    row = {
        "pair_id": "p01:j1",
        "label": 2,
        "reason": "Fine.",
        "confidence": "high",
        "provider": "gemini",
        "model": "m",
        "prompt": "eval_judge/v1",
        "field_from_2027": 1,
    }
    path = tmp_path / "judge.jsonl"
    path.write_text(json.dumps(row) + "\n")
    with pytest.raises(StaleCodeError, match="field_from_2027"):
        load_judge(path)


def test_every_eval_make_target_runs_the_current_code() -> None:
    makefile = Path(__file__).resolve().parents[2] / "Makefile"
    if not makefile.exists():  # inside the container only backend/ is present
        pytest.skip("Makefile not available")
    text = makefile.read_text(encoding="utf-8")
    run = next(line for line in text.splitlines() if line.startswith("EVAL_RUN ="))
    assert "-v ./backend/app:/app/app" in run
    eval_lines = [line for line in text.splitlines() if "app.eval.cli" in line]
    assert eval_lines
    assert all(line.strip().startswith("$(EVAL_RUN)") for line in eval_lines)
