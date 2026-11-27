"""PREVIEW agreement on the blind pairs where all three judges have a grade made from the
same judge input as Gemini's final label (input_sha256 equal). Not the final numbers:
those come from the report once every judge has finished.

    python -m scripts.preview_agreement [--set eval-2026-11-25] [--out PATH]
"""

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from app.eval import EVAL_DIR
from app.eval.agreement import JUDGES, Facts, agreement_report
from app.eval.report import agreement_lines, label_sets


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--set", default="eval-2026-11-25")
    parser.add_argument("--out", default=None)
    args = parser.parse_args()
    folder = EVAL_DIR / "labels" / args.set
    blind = json.loads((folder / "plan.json").read_text(encoding="utf-8"))["blind"]
    sets = label_sets(folder)
    ref = sets["final"]["gemini"]
    matched = {
        name: {
            pid: r.label
            for pid, r in sets["final"][name].items()
            if pid in ref and r.input_sha256 and r.input_sha256 == ref[pid].input_sha256
        }
        for name in JUDGES
    }
    common = [p for p in blind if all(p in matched[n] for n in JUDGES)]
    reasons = {n: {p: r.reason for p, r in sets["final"][n].items()} for n in JUDGES}
    index = folder / "export" / "pairs_index.jsonl"
    strata = {
        r["pair_id"]: r["strata"]
        for r in (json.loads(x) for x in index.read_text(encoding="utf-8").splitlines() if x)
    }
    report = agreement_report(common, matched, Facts(strata=strata, reasons=reasons))
    stamp = datetime.now(UTC).isoformat(timespec="minutes")
    lines = [
        f"# PREVIEW agreement (not final): {args.set}, {stamp}",
        "",
        f"Blind pairs where Gemini, Groq and Claude Cowork all have a grade made from the "
        f"same judge input (equal input_sha256): **n = {len(common)} of {len(blind)}**. "
        "LLM-judged; no human labels. Final numbers come from the report once every "
        "judge has finished.",
        "",
        *agreement_lines({"blind": report}),
    ]
    text = "\n".join(lines) + "\n"
    out = Path(args.out) if args.out else None
    if out:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
    for p in report["pairwise"]:
        ci = p["weighted_kappa_ci95"]
        print(
            f"{p['a']} vs {p['b']}: n={p['n']}, kappa {p['weighted_kappa']:.3f} "
            f"[{ci[0]:.3f}, {ci[1]:.3f}], exact {p['exact']:.1%}"
        )
    print(f"common n={len(common)}; majority {report.get('majority')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
