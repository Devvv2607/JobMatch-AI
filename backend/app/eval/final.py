"""The final Phase 4 run, end to end (owner, 2026-11-27): `make eval-final`.

1. verify: every judge file is complete, has no duplicate pair, ends with a complete
   line, and every grade's input_sha256 matches the input it claims (v2 or v3); no
   failure files; all three judges have a hash-matched grade on all 120 blind pairs;
2. export the committed form of the label set;
3. build the report: metrics with CIs, judged@10, subsets, sensitivity (v2 vs final
   labels), agreement before/after on identical pairs with the paired change in kappa,
   robustness, ADR 0003; write eval/reports/<date>-<commit>.json and .md;
4. fill the marked blocks (<!-- BEGIN:name --> ... <!-- END:name -->) in eval/report.md,
   docs/decisions/0003-rerank-profiles.md and docs/claims.md.

With preview=True nothing committed is touched: verification problems are listed, not
fatal, and every output goes to eval/private/preview/.
"""

import json
import re
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.eval import EVAL_DIR
from app.eval.judge import input_hash, pair_input
from app.eval.pairs import load_pairs, read_jsonl
from app.eval.profiles import load_profiles
from app.eval.report import V3_FILES, build, markdown
from app.eval.until_done import last_line_ok

REPO = EVAL_DIR.parent
TARGETS = {
    "report": EVAL_DIR / "report.md",
    "adr": REPO / "docs" / "decisions" / "0003-rerank-profiles.md",
    "claims": REPO / "docs" / "claims.md",
}
# Block name -> the generated report's section heading prefix(es).
SECTIONS = {
    "labels": ["## Labels"],
    "input-fix": ["## The input fix"],
    "key-results": ["## Key results"],
    "metrics": [
        "## Metrics, LLM-judged (Gemini), primary",
        "## Metrics, LLM-judged (Gemini), check",
    ],
    "comparisons": ["## Comparisons"],
    "subsets": ["## Subsets"],
    "sensitivity": ["## Sensitivity"],
    "adr": ["## ADR 0003"],
    "agreement": ["## Agreement between the LLM judges"],
    "robustness": ["## Robustness"],
}
BLOCK = re.compile(
    r"(<!-- BEGIN:(?P<name>[\w-]+) -->\n)(?P<body>.*?)(<!-- END:(?P=name) -->)", re.S
)


def records(path: Path) -> list[dict[str, Any]]:
    return [dict(r) for r in read_jsonl(path)]


def verify(folder: Path) -> tuple[list[str], dict[str, Any]]:
    """(problems, counts). No problems means the label set is complete and consistent."""
    problems: list[str] = []
    pairs = {p.pair_id: p for p in load_pairs(folder / "pairs.jsonl")}
    profiles = load_profiles()
    hashes = {
        pid: {v: input_hash(pair_input(profiles[p.profile_id], p, v)) for v in (2, 3)}
        for pid, p in pairs.items()
    }
    blind = json.loads((folder / "plan.json").read_text(encoding="utf-8"))["blind"]
    cut = set((folder / "cut-ids.txt").read_text(encoding="utf-8").split())
    blind_cut = cut & set(blind)
    wanted = {
        "judge.jsonl": (set(pairs), 2),
        "judge-groq-blind.jsonl": (set(blind), 2),
        V3_FILES["gemini"]: (cut, 3),
        V3_FILES["groq"]: (blind_cut, 3),
    }
    counts: dict[str, Any] = {"pairs": len(pairs), "cut": len(cut), "blind": len(blind)}
    for file, (want, version) in wanted.items():
        path = folder / file
        if not last_line_ok(path):
            problems.append(f"{file}: last line incomplete")
            continue
        rows = records(path)
        ids = [str(r["pair_id"]) for r in rows]
        dupes = len(ids) - len(set(ids))
        missing = want - set(ids)
        wrong = sum(
            1
            for r in rows
            if str(r["pair_id"]) in hashes
            and r.get("input_sha256") != hashes[str(r["pair_id"])][version]
        )
        counts[file] = {"records": len(rows), "missing": len(missing), "dupes": dupes}
        if dupes:
            problems.append(f"{file}: {dupes} duplicate pair ids")
        if missing:
            problems.append(f"{file}: {len(missing)} of {len(want)} pairs not judged")
        if wrong:
            problems.append(
                f"{file}: {wrong} grades whose input_sha256 is not the v{version} input"
            )
    # Claude Cowork: every blind pair needs a grade made from the final input.
    cowork = {str(r["pair_id"]): r for r in records(folder / "judge-claude-cowork.jsonl")}
    cowork.update({str(r["pair_id"]): r for r in records(folder / V3_FILES["cowork"])})
    final_hash = {p: hashes[p][3] for p in blind}  # v3 == v2 for uncut pairs
    matched = sum(1 for p in blind if cowork.get(p, {}).get("input_sha256") == final_hash[p])
    counts["cowork_blind_hash_matched"] = matched
    if matched < len(blind):
        problems.append(
            f"Claude Cowork: {len(blind) - matched} blind pairs without a hash-matched grade"
        )
    for failures in folder.glob("*failures*.jsonl"):
        if failures.stat().st_size:
            problems.append(f"{failures.name}: not empty")
    return problems, counts


def sections(md: str) -> dict[str, str]:
    """Generated report markdown split by '## ' heading (heading line included)."""
    out: dict[str, str] = {}
    head: str | None = None
    lines: list[str] = []
    for line in md.splitlines():
        if line.startswith("## "):
            if head is not None:
                out[head] = "\n".join(lines)
            head, lines = line, [line]
        elif head is not None:
            lines.append(line)
    if head is not None:
        out[head] = "\n".join(lines)
    return out


def demote(text: str) -> str:
    """Headings one level down, so a generated '## X' sits under the page's own '## N.'."""
    return "\n".join("#" + line if line.startswith("#") else line for line in text.splitlines())


def blocks_from(md: str, report: Mapping[str, Any], status: str) -> dict[str, str]:
    found = sections(md)
    blocks = {"status": status}
    for name, prefixes in SECTIONS.items():
        parts = [
            demote(body)
            for head, body in found.items()
            if any(head.startswith(p) for p in prefixes)
        ]
        if parts:
            blocks[name] = "\n\n".join(p.strip() for p in parts)
    rb = report["robustness"]["rerank_choice"]
    v2 = report["rerank_choice"].get("query (v2 labels)", {}).get("chosen")
    blocks["adr"] = (
        blocks.get("adr", "")
        + "\n\nRobustness of the choice (same rule): "
        + ", ".join(f"{j}: `{c}`" for j, c in rb.items())
        + (f"; under the v2 labels: `{v2}`." if v2 else ".")
    )
    blocks["claims-numbers"] = claims_numbers(report)
    return blocks


def _ci(est: Mapping[str, Any] | None, signed: bool = False) -> str:
    if not est:
        return "-"
    f = "{:+.3f}" if signed else "{:.3f}"
    return f"{f.format(est['mean'])} [{f.format(est['ci_low'])}, {f.format(est['ci_high'])}]"


def claims_numbers(r: Mapping[str, Any]) -> str:
    """The measured numbers each claim template needs, with where they come from."""
    v = r["metrics"]["unjudged0"]["variants"]
    c = r["metrics"]["unjudged0"]["comparisons"]
    choice = r["rerank_choice"]["query"]
    chosen = choice["chosen"]
    judged = [row["judged10"]["mean"] for row in v.values() if row.get("judged10")]
    kappas = [
        x["weighted_kappa"]
        for x in r["agreement"]["blind"]["pairwise"]
        if x["weighted_kappa"] is not None
    ]
    rows = [
        ("keyword NDCG@10 (query)", _ci(v["query:bm25"]["ndcg10"])),
        ("hybrid NDCG@10 (query)", _ci(v["query:fused"]["ndcg10"])),
        ("hybrid vs keyword (paired)", _ci(c["query: hybrid vs keyword"]["ndcg10"], True)),
        (f"chosen rerank `{chosen}` NDCG@10", _ci(v[f"query:{chosen}"]["ndcg10"])),
        ("+personalisation vs hybrid", _ci(c["query: +personalisation vs hybrid"]["ndcg10"], True)),
        (
            "chosen setting p95 (ms)",
            f"{choice['chosen_p95_ms']:.0f} "
            f"({'meets' if choice['meets_300ms'] else 'misses'} 300 ms)",
        ),
        ("judged@10, lowest variant", f"{min(judged):.2f}" if judged else "-"),
        ("pairs (all LLM-judged)", str(r["pairs"]["total"])),
        ("blind pairs in the final agreement (hash-identical)", str(r["agreement_pairs"])),
        (
            "inter-judge weighted kappa, range",
            f"{min(kappas):.2f}-{max(kappas):.2f}" if kappas else "-",
        ),
    ]
    for ch in r["agreement_change"]:
        d = (
            "-"
            if ch["delta"] is None
            else f"{ch['delta']:+.3f} [{ch['ci95'][0]:+.3f}, {ch['ci95'][1]:+.3f}] {ch['verdict']}"
        )
        rows.append((f"kappa change after the input fix, {ch['a']} vs {ch['b']} (n={ch['n']})", d))
    lines = [
        f"Measured {r['generated_at']} at commit {r['commit']} (report "
        f"`eval/reports/{r['generated_at'][:10]}-{r['commit']}.md`). LLM-judged (Gemini).",
        "",
        "| Quantity | Value |",
        "|---|---|",
        *[f"| {k} | {val} |" for k, val in rows],
    ]
    return "\n".join(lines)


def fill(text: str, blocks: Mapping[str, str]) -> tuple[str, list[str]]:
    """Replace each BEGIN/END block whose name is in `blocks`; returns (text, filled)."""
    filled: list[str] = []

    def sub(m: re.Match[str]) -> str:
        name = m.group("name")
        if name not in blocks:
            return m.group(0)
        filled.append(name)
        return f"{m.group(1)}{blocks[name].rstrip()}\n{m.group(4)}"

    return BLOCK.sub(sub, text), filled


def run(name: str, commit: str, *, preview: bool) -> int:
    from app.eval.export import export_set, pairs_index

    folder = EVAL_DIR / "labels" / name
    problems, counts = verify(folder)
    print("verify:", json.dumps(counts))
    for p in problems:
        print(f"  {'PREVIEW, not final: ' if preview else 'FAIL: '}{p}")
    if problems and not preview:
        print("final run stopped: fix the problems above (or run with --preview)")
        return 1
    out_dir = EVAL_DIR / "private" / "preview" if preview else EVAL_DIR / "reports"
    out_dir.mkdir(parents=True, exist_ok=True)
    if preview:
        index = out_dir / "pairs_index.jsonl"
        rows = pairs_index(load_pairs(folder / "pairs.jsonl"))
        index.write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in rows))
    else:
        export_set(folder, load_pairs(folder / "pairs.jsonl"))
        index = folder / "export" / "pairs_index.jsonl"
    pending = "; ".join(problems) if problems else None
    report = build(folder, commit, pending=pending, index_path=index)
    stamp = f"{datetime.now(UTC):%Y-%m-%d}-{commit}"
    commands = [
        f"make eval-final SET={name}" + (" PREVIEW=1" if preview else ""),
        f"python -m app.eval.cli agreement --set {name}",
        "make eval   # the CI gate on the reduced corpus",
    ]
    md = markdown(report, commands)
    (out_dir / f"{stamp}.json").write_text(json.dumps(report, indent=1) + "\n")
    (out_dir / f"{stamp}.md").write_text(md, encoding="utf-8")
    status = (
        f"_PREVIEW on incomplete labels ({len(problems)} open items): not final._"
        if preview
        else f"_Final run {report['generated_at']}, commit {commit}: `eval/reports/{stamp}.md`._"
    )
    blocks = blocks_from(md, report, status)
    for target, path in TARGETS.items():
        text, filled = fill(path.read_text(encoding="utf-8"), blocks)
        dest = out_dir / f"{stamp}-{target}.md" if preview else path
        dest.write_text(text, encoding="utf-8", newline="\n")
        print(f"{target}: filled {filled} -> {dest}")
    print(f"report: {out_dir / f'{stamp}.md'}")
    return 0
