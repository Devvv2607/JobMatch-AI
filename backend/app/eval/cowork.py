"""Claude Cowork as a third LLM judge (owner decision 2026-11-27).

Claude Cowork (an AI agent) grades pairs in spreadsheets, never in the labelling tool:
its grades are judge records (provider "claude-cowork", label_source "llm") in
eval/labels/<set>/judge-claude-cowork.jsonl, and nothing here reads or writes
human.jsonl.

Export: eval/private/cowork/ (gitignored, the sheets quote postings):
- batch-00.xlsx: the blind pairs Cowork has not graded yet (in blind order);
- batch-01.xlsx ...: the other pairs it has not graded, in a seeded shuffle, split
  into near-equal batches of about `per_batch`;
- manifest.json: the pair ids of every batch, so an import is checked against them.
Each batch sheet has the columns pair_id, profile, job, grade, reason, confidence;
profile and job are exactly the "candidate" and "job" objects the judge prompt receives
(app/eval/judge.py pair_input). A "Rubric" sheet holds the judge prompt verbatim. No
system rank or score, no retriever and no other judge's label is in a sheet.

Import: one filled sheet; each row is checked (pair id in that batch, no duplicate,
grade 0-3, reason of at most 60 words, confidence high/medium/low) and accepted rows
are appended to judge-claude-cowork.jsonl. Rejected rows are reported, not written.
"""

import json
import random
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.eval.judge import INPUT_VERSION, PROMPT_NAME, PROMPT_VERSION, pair_input
from app.eval.pairs import EvalPair, JudgeRecord, append_jsonl, load_judge
from app.eval.profiles import EvalProfile

PROVIDER = "claude-cowork"
JUDGE_FILE = "judge-claude-cowork.jsonl"
COLUMNS = ("pair_id", "profile", "job", "grade", "reason", "confidence")
CONFIDENCE = ("high", "medium", "low")
MAX_REASON_WORDS = 60
SHEET = "Pairs"
RUBRIC_SHEET = "Rubric"
BATCH_NAME = re.compile(r"batch-(\d{2})")


def sheet_cells(
    profile: EvalProfile, pair: EvalPair, input_version: int = INPUT_VERSION
) -> tuple[str, str]:
    """The candidate and job objects of the judge's user message, as indented JSON."""
    body = (
        pair_input(profile, pair, input_version).removeprefix("<pair>\n").removesuffix("\n</pair>")
    )
    data = json.loads(body)
    return (
        json.dumps(data["candidate"], ensure_ascii=False, indent=1),
        json.dumps(data["job"], ensure_ascii=False, indent=1),
    )


def plan_batches(
    pairs: list[EvalPair],
    blind: list[str],
    graded: set[str],
    *,
    per_batch: int = 95,
    seed: int = 27,
) -> list[list[str]]:
    """Batch 0: ungraded blind pairs in blind order. Then every other ungraded pair, in
    a seeded shuffle (not grouped by profile), split into near-equal batches."""
    blind_set = set(blind)
    first = [pid for pid in blind if pid not in graded]
    rest = [p.pair_id for p in pairs if p.pair_id not in blind_set and p.pair_id not in graded]
    random.Random(seed).shuffle(rest)  # noqa: S311 - a reproducible order, not security
    n = max(1, round(len(rest) / per_batch)) if rest else 0
    size, extra = divmod(len(rest), n) if n else (0, 0)
    batches, start = [first], 0
    for i in range(n):
        end = start + size + (1 if i < extra else 0)
        batches.append(rest[start:end])
        start = end
    return batches


def write_workbook(path: Path, rows: list[tuple[str, str, str]], rubric: str) -> None:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font
    from openpyxl.worksheet.datavalidation import DataValidation

    wb = Workbook()
    ws = wb.create_sheet(SHEET, 0)
    for extra in wb.worksheets[1:]:
        wb.remove(extra)  # the default empty sheet
    ws.append(list(COLUMNS))
    for cell in ws[1]:
        cell.font = Font(bold=True)
    for pid, candidate, job in rows:
        ws.append([pid, candidate, job, None, None, None])
    widths = {"A": 24, "B": 60, "C": 80, "D": 8, "E": 50, "F": 12}
    for col, width in widths.items():
        ws.column_dimensions[col].width = width
    for row in ws.iter_rows(min_row=2):
        for cell in row:
            cell.alignment = Alignment(wrap_text=True, vertical="top")
    ws.freeze_panes = "B2"
    last = len(rows) + 1
    grade = DataValidation(type="whole", operator="between", formula1="0", formula2="3")
    grade.add(f"D2:D{last}")
    confidence = DataValidation(type="list", formula1='"high,medium,low"')
    confidence.add(f"F2:F{last}")
    ws.add_data_validation(grade)
    ws.add_data_validation(confidence)
    rubric_ws = wb.create_sheet(RUBRIC_SHEET)
    rubric_ws.column_dimensions["A"].width = 140
    for line in rubric.splitlines():
        rubric_ws.append([line])
    for row in rubric_ws.iter_rows():
        row[0].alignment = Alignment(wrap_text=True, vertical="top")
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)


def export_batches(
    out_dir: Path,
    pairs: list[EvalPair],
    profiles: dict[str, EvalProfile],
    blind: list[str],
    graded: set[str],
    rubric: str,
    *,
    per_batch: int = 95,
    seed: int = 27,
) -> dict[str, list[str]]:
    """Writes batch-NN.xlsx and manifest.json; refuses to overwrite an existing sheet
    (it may already hold grades)."""
    by_id = {p.pair_id: p for p in pairs}
    batches = plan_batches(pairs, blind, graded, per_batch=per_batch, seed=seed)
    names = {f"batch-{i:02d}": ids for i, ids in enumerate(batches) if ids}
    existing = [n for n in names if (out_dir / f"{n}.xlsx").exists()]
    if existing or (out_dir / "manifest.json").exists():
        raise FileExistsError(f"{out_dir} already has sheets ({existing or 'manifest.json'})")
    for name, ids in names.items():
        rows = [(pid, *sheet_cells(profiles[by_id[pid].profile_id], by_id[pid])) for pid in ids]
        write_workbook(out_dir / f"{name}.xlsx", rows, rubric)
    manifest = {"seed": seed, "per_batch": per_batch, "batches": names}
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=1) + "\n")
    return names


@dataclass
class ImportReport:
    batch: str
    expected: int
    accepted: list[JudgeRecord] = field(default_factory=list)
    already: int = 0  # identical to a record already imported: skipped
    ungraded: list[str] = field(default_factory=list)  # rows left blank
    rejected: list[tuple[int, str, str]] = field(default_factory=list)  # (row, pair id, why)
    missing: list[str] = field(default_factory=list)  # batch pairs with no row at all

    def distribution(self) -> dict[int, int]:
        counts = Counter(r.label for r in self.accepted)
        return {g: counts.get(g, 0) for g in range(4)}

    def confidences(self) -> dict[str, int]:
        counts = Counter(str(r.confidence) for r in self.accepted)
        return {c: counts.get(c, 0) for c in CONFIDENCE}


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _grade(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    text = _text(value)
    return int(text) if re.fullmatch(r"\d", text) else None


def read_rows(path: Path) -> list[dict[str, Any]]:
    from openpyxl import load_workbook

    wb = load_workbook(path, read_only=True, data_only=True)
    ws = wb[SHEET] if SHEET in wb.sheetnames else wb.worksheets[0]
    rows = ws.iter_rows(values_only=True)
    header = [_text(h).lower() for h in next(rows)]
    missing = [c for c in COLUMNS if c not in header]
    if missing:
        raise ValueError(f"{path.name}: missing columns {missing}")
    out = [dict(zip(header, row, strict=False)) for row in rows]
    wb.close()
    return out


def check_rows(
    batch: str,
    rows: list[dict[str, Any]],
    expected: list[str],
    imported: dict[str, JudgeRecord],
    input_version: int = INPUT_VERSION,
    hashes: dict[str, str] | None = None,
) -> ImportReport:
    report = ImportReport(batch=batch, expected=len(expected))
    wanted = set(expected)
    seen: set[str] = set()
    for number, row in enumerate(rows, start=2):  # spreadsheet row numbers
        pid = _text(row.get("pair_id"))
        grade_cell, reason, conf = row.get("grade"), _text(row.get("reason")), row.get("confidence")
        if not pid and grade_cell is None and not reason:
            continue  # an empty line
        if pid not in wanted:
            report.rejected.append((number, pid, f"pair id not in {batch}"))
            continue
        if pid in seen:
            report.rejected.append((number, pid, "duplicate row for this pair"))
            continue
        seen.add(pid)
        if _text(grade_cell) == "" and not reason:
            report.ungraded.append(pid)
            continue
        grade = _grade(grade_cell)
        problems = []
        if grade is None or not 0 <= grade <= 3:
            problems.append(f"grade {grade_cell!r} is not 0-3")
        if not reason:
            problems.append("no reason")
        elif len(reason.split()) > MAX_REASON_WORDS:
            problems.append(f"reason has {len(reason.split())} words (max {MAX_REASON_WORDS})")
        confidence = _text(conf).lower()
        if confidence not in CONFIDENCE:
            problems.append(f"confidence {conf!r} is not high/medium/low")
        if problems or grade is None:
            report.rejected.append((number, pid, "; ".join(problems)))
            continue
        record = JudgeRecord(
            pair_id=pid,
            label=grade,
            reason=reason,
            confidence=confidence,  # checked above
            provider=PROVIDER,
            model=PROVIDER,
            prompt=f"{PROMPT_NAME}/v{PROMPT_VERSION}+input{input_version}; sheet {batch}",
            input_sha256=(hashes or {}).get(pid),
            label_source="llm",
        )
        if pid in imported:
            old = imported[pid]
            if (old.label, old.reason, old.confidence) == (grade, reason, confidence):
                report.already += 1
            else:
                report.rejected.append((number, pid, "already imported with a different grade"))
            continue
        report.accepted.append(record)
    report.missing = [pid for pid in expected if pid not in seen]
    return report


def batch_of(path: Path) -> str:
    match = BATCH_NAME.search(path.stem)
    if not match:
        raise ValueError(f"{path.name}: the file name must contain batch-NN")
    return match.group(0)


def import_sheet(
    path: Path,
    folder: Path,
    manifest_path: Path,
    hashes: dict[str, dict[int, str]] | None = None,
) -> ImportReport:
    """Checks one filled sheet against its batch and appends the accepted rows to the
    batch's judge file (judge-claude-cowork.jsonl unless the manifest names another).
    Only that file is written. `hashes`: pair id -> input version -> judge input hash."""
    batch = batch_of(path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if batch in manifest.get("cancelled", []):
        raise ValueError(f"{batch} was cancelled (owner decision); nothing imported")
    if batch not in manifest["batches"]:
        raise ValueError(f"{batch} is not in {manifest_path}")
    meta = manifest.get("meta", {}).get(batch, {})
    version = int(meta.get("input_version", INPUT_VERSION))
    out = folder / meta.get("judge_file", JUDGE_FILE)
    rows = read_rows(path)
    if not any(_text(r.get("grade")) or _text(r.get("reason")) for r in rows):
        raise ValueError(f"{path.name} has no grades yet: nothing imported")
    report = check_rows(
        batch,
        rows,
        manifest["batches"][batch],
        load_judge(out),
        version,
        {pid: h[version] for pid, h in (hashes or {}).items() if version in h},
    )
    for record in report.accepted:
        append_jsonl(out, record)
    return report


def export_named_batch(
    out_dir: Path,
    name: str,
    ids: list[str],
    pairs: list[EvalPair],
    profiles: dict[str, EvalProfile],
    rubric: str,
    *,
    input_version: int,
    judge_file: str,
) -> None:
    """One more batch with its own input version and judge file, added to manifest.json
    (owner decision 2026-11-27: batch-05 = the cut blind pairs on input v3, graded into
    judge-claude-cowork-v3.jsonl). Refuses to overwrite a sheet."""
    path = out_dir / f"{name}.xlsx"
    if path.exists():
        raise FileExistsError(f"{path} exists")
    by_id = {p.pair_id: p for p in pairs}
    rows = [
        (pid, *sheet_cells(profiles[by_id[pid].profile_id], by_id[pid], input_version))
        for pid in ids
    ]
    write_workbook(path, rows, rubric)
    manifest_path = out_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["batches"][name] = ids
    manifest.setdefault("meta", {})[name] = {
        "input_version": input_version,
        "judge_file": judge_file,
    }
    manifest_path.write_text(json.dumps(manifest, indent=1) + "\n")


def cancel_batches(out_dir: Path, names: list[str]) -> list[str]:
    """Marks batches cancelled in manifest.json and moves their sheets to cancelled/."""
    manifest_path = out_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    moved = []
    for name in names:
        if name not in manifest.get("cancelled", []):
            manifest.setdefault("cancelled", []).append(name)
        sheet = out_dir / f"{name}.xlsx"
        if sheet.exists():
            (out_dir / "cancelled").mkdir(exist_ok=True)
            sheet.rename(out_dir / "cancelled" / sheet.name)
            moved.append(sheet.name)
    manifest_path.write_text(json.dumps(manifest, indent=1) + "\n")
    return moved
