"""The Phase 4 report: eval/reports/<date>-<commit>.json and .md (brief item 9).

Everything is computed from committed files: the set's runs.jsonl (every variant's
ranking on the frozen snapshot), plan.json (the blind pairs), export/pairs_index.jsonl
and the judges' label files. Every metric is LLM-judged; the primary labels are Gemini's.
There are no human relevance labels (owner decision 2026-11-27).
"""

import json
from collections import Counter
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

from app.eval.agreement import JUDGES, Facts, agreement_report, kappa_change, majority
from app.eval.evaluate import (
    LATENCY_SOURCE,
    METRICS,
    STEPS,
    TARGET_P95_MS,
    choose_rerank,
    evaluate,
    load_runs,
    restrict,
    robustness,
)
from app.eval.pairs import JudgeRecord, read_jsonl

PRIMARY = "gemini"
JUDGE_NAMES = {
    "gemini": "Gemini (gemini-3.5-flash-lite)",
    "groq": "Groq (openai/gpt-oss-120b)",
    "cowork": "Claude Cowork (AI agent)",
    "majority": "3-judge majority (median)",
}
METRIC_NAMES = {"ndcg10": "NDCG@10", "mrr": "MRR", "recall30": "Recall@30"}
MAIN = [
    "hybrid vs keyword",
    "vector vs keyword",
    "hybrid vs vector",
    "+personalisation vs hybrid",
    "+rerank 10@128 vs +personalisation",
    "+rerank 20@128 vs +personalisation",
    "+rerank 30@256 vs +personalisation",
]
LIMITATIONS = [
    "No human relevance labels: every grade is an LLM's (Gemini primary; Groq and Claude "
    "Cowork for agreement and robustness). The judges share one rubric and may share "
    "biases; agreement between them is not agreement with people.",
    "25 fictional profiles (about 70% India-based); confidence intervals are over these 25 "
    "profiles and do not cover other kinds of job seeker.",
    "One frozen snapshot of the job pool (2026-11-25); the pool changes daily.",
    "Rankings are the API's top 30, so recall is Recall@30 over judged relevant jobs "
    "(grade >= 2), not Recall@50.",
    "Latency comes from the 2026-11-24 benchmark (11,531-job pool) on the owner's laptop, "
    "not from the snapshot (23,705 searchable jobs).",
    "Claude Cowork's first 118 grades were made from the labelling tool's card, without a "
    "confidence; its later batches use the judge's exact input.",
]
DEFERRED = [
    "Cold vs warm personalisation (simulated saved jobs).",
    "source_quality and down-rank gig/agency ablations.",
    "The int8 and TinyBERT-L-2-v2 rows of ADR 0003 (models not built yet).",
]


def load_labels(folder: Path) -> dict[str, dict[str, int]]:
    out: dict[str, dict[str, int]] = {}
    for name, file in JUDGES.items():
        rows = (JudgeRecord.model_validate(r) for r in read_jsonl(folder / file))
        out[name] = {r.pair_id: r.label for r in rows}
    return out


def job_facts(corpus: Path) -> dict[str, dict[str, str]]:
    """source, description_quality and posted_at of every job in the reduced corpus,
    which holds every job any variant ranked (app/eval/reduced.py)."""
    import csv
    import gzip
    import io

    csv.field_size_limit(2**31 - 1)  # descriptions can be long; C long on Windows
    data = gzip.decompress((corpus / "jobs.csv.gz").read_bytes()).decode("utf-8")
    return {
        row["id"]: {
            "source": row["source"],
            "quality": row["description_quality"],
            "posted_at": row["posted_at"],
        }
        for row in csv.DictReader(io.StringIO(data))
    }


SUBSETS = {
    "all pairs": "every job",
    "without source snippets": "jobs whose source gives only a snippet "
    "(description_quality = snippet: Adzuna) removed",
    "posted within 90 days": "jobs posted more than 90 days before the snapshot removed",
}


def subset_drops(facts: Mapping[str, Mapping[str, str]], snapshot_day: str) -> dict[str, set[str]]:
    cutoff = datetime.fromisoformat(snapshot_day).replace(tzinfo=UTC) - timedelta(days=90)
    stale = set()
    for job, f in facts.items():
        if f["posted_at"]:
            posted = datetime.fromisoformat(f["posted_at"].replace(" ", "T"))
            if posted.tzinfo is None:
                posted = posted.replace(tzinfo=UTC)
            if posted < cutoff:
                stale.add(job)
    return {
        "all pairs": set(),
        "without source snippets": {j for j, f in facts.items() if f["quality"] == "snippet"},
        "posted within 90 days": stale,
    }


def subsets(
    runs: Mapping[str, Any], labels: Mapping[str, int], drops: Mapping[str, set[str]]
) -> dict[str, Any]:
    """The main query-mode numbers on each subset (condensed lists)."""
    out: dict[str, Any] = {}
    for name, drop in drops.items():
        r_runs, r_labels = restrict(runs, labels, drop)
        result = evaluate(r_runs, r_labels, "condensed")
        out[name] = {
            "description": SUBSETS[name],
            "dropped_jobs": len(drop),
            "labelled_pairs": len(r_labels),
            "ndcg10": {
                v: result["variants"][f"query:{v}"]["ndcg10"]
                for _, v in STEPS
                if f"query:{v}" in result["variants"]
            },
            "comparisons": {
                k: c["ndcg10"]
                for k, c in result["comparisons"].items()
                if k.startswith("query: ") and any(k.endswith(m) for m in MAIN)
            },
        }
    return out


def _clean(result: Mapping[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in result.items() if not k.startswith("_")}


# Input v3 re-judgements (owner decision 2026-11-27): for the pairs whose description input
# v2 cut, these files override the v2 label; every other pair's v3 input equals its v2
# input (same sha256), so its v2 label stands.
V3_FILES = {
    "gemini": "judge-v3.jsonl",
    "groq": "judge-groq-blind-v3.jsonl",
    "cowork": "judge-claude-cowork-v3.jsonl",
}


def read_records(path: Path) -> dict[str, JudgeRecord]:
    return {r.pair_id: r for r in (JudgeRecord.model_validate(x) for x in read_jsonl(path))}


def label_sets(folder: Path) -> dict[str, dict[str, dict[str, JudgeRecord]]]:
    """{"v2": judge -> records, "final": judge -> v2 records overridden by v3 ones}."""
    v2 = {name: read_records(folder / file) for name, file in JUDGES.items()}
    final = {name: {**v2[name], **read_records(folder / V3_FILES[name])} for name in JUDGES}
    return {"v2": v2, "final": final}


def grades_of(records: Mapping[str, JudgeRecord]) -> dict[str, int]:
    return {pid: r.label for pid, r in records.items()}


def input_fix(folder: Path, sets: Mapping[str, Any], cut: set[str]) -> dict[str, Any]:
    """The v2 -> v3 finding: the controlled check, the long-text noise re-run, and the
    change rate over every cut pair Gemini re-judged."""
    check = json.loads((folder / "check-v3-result.json").read_text(encoding="utf-8"))
    v2 = sets["v2"]["gemini"]
    v3 = read_records(folder / V3_FILES["gemini"])
    noise_file = folder / "judge-v3-noise.jsonl"
    noise = read_records(noise_file) if noise_file.exists() else {}
    noise_changed = [p for p, r in noise.items() if p in v3 and v3[p].label != r.label]
    done = [p for p in cut if p in v3]
    changed = [p for p in done if v3[p].label != v2[p].label]
    return {
        "cut_pairs": len(cut),
        "cut_rejudged": len(done),
        "controlled_check": {
            k: {kk: vv for kk, vv in v.items() if kk != "examples"} if isinstance(v, dict) else v
            for k, v in check.items()
        },
        "noise_rerun": {"pairs": len(noise), "changed": len(noise_changed)},
        "all_cut": {
            "changed": len(changed),
            "rate": len(changed) / len(done) if done else None,
            "down": sum(v3[p].label < v2[p].label for p in changed),
            "up": sum(v3[p].label > v2[p].label for p in changed),
            "transitions": dict(Counter(f"{v2[p].label}->{v3[p].label}" for p in changed)),
        },
    }


def sensitivity(final: Mapping[str, Any], v2: Mapping[str, Any]) -> dict[str, Any]:
    """Main numbers under the final labels and under the v2 labels, and the deltas."""
    rows: dict[str, Any] = {}
    for v, f in final["variants"].items():
        a, b = f["ndcg10"], v2["variants"].get(v, {}).get("ndcg10")
        if a and b:
            rows[v] = {"final": a["mean"], "v2": b["mean"], "delta": a["mean"] - b["mean"]}
    comps: dict[str, Any] = {}
    for name, c in final["comparisons"].items():
        a, b = c.get("ndcg10"), v2["comparisons"].get(name, {}).get("ndcg10")
        if a and b:
            comps[name] = {
                "final": a,
                "v2": b,
                "delta": a["mean"] - b["mean"],
                "same_verdict": a["verdict"] == b["verdict"],
            }
    return {"ndcg10": rows, "comparisons": comps}


def build(folder: Path, commit: str, pending: str | None = None) -> dict[str, Any]:
    plan = json.loads((folder / "plan.json").read_text(encoding="utf-8"))
    pool = json.loads((folder / "pool.json").read_text(encoding="utf-8"))
    index = list(read_jsonl(folder / "export" / "pairs_index.jsonl"))
    strata: dict[str, dict[str, str]] = {
        str(r["pair_id"]): cast(dict[str, str], r["strata"]) for r in index
    }
    pooled = [pid for pid, s in strata.items() if s.get("pool") is None]
    every = list(strata)
    blind = list(plan["blind"])
    blind_set = set(blind)
    cut_file = folder / "cut-ids.txt"
    cut = set(cut_file.read_text(encoding="utf-8").split()) if cut_file.exists() else set()
    runs = load_runs(folder / "runs.jsonl")
    sets = label_sets(folder)
    labels = {name: grades_of(r) for name, r in sets["final"].items()}
    labels_v2 = {name: grades_of(r) for name, r in sets["v2"].items()}

    def facts_for(records: Mapping[str, Mapping[str, JudgeRecord]]) -> Facts:
        reasons = {n: {p: r.reason for p, r in recs.items()} for n, recs in records.items()}
        return Facts(strata=strata, reasons=reasons)

    primary = {c: evaluate(runs, labels[PRIMARY], c) for c in ("unjudged0", "condensed")}
    baseline_v2 = evaluate(runs, labels_v2[PRIMARY], "unjudged0")
    # Owner 2026-11-27: on the blind pairs, a grade counts only if it was made from the
    # same judge input as Gemini's final label (equal input_sha256), so all three judges
    # are compared on hash-identical input.
    ref = sets["final"][PRIMARY]
    matched = {
        name: {
            pid: r.label
            for pid, r in sets["final"][name].items()
            if pid in blind_set
            and r.input_sha256 is not None
            and pid in ref
            and r.input_sha256 == ref[pid].input_sha256
        }
        for name in JUDGES
    }
    hash_matched = {
        name: {"blind_graded": sum(p in blind_set for p in sets["final"][name]), "used": len(g)}
        for name, g in matched.items()
    }
    on_blind = dict(matched)
    # Like-for-like (owner 2026-11-27): before and after on the same pairs, the blind
    # pairs where every judge has a hash-identical final grade.
    common = [p for p in blind if all(p in matched[n] for n in JUDGES)]
    on_blind["majority"] = majority(blind, {n: on_blind[n] for n in JUDGES})
    robust_results = {"gemini (all pairs)": primary["unjudged0"]}
    for name, grades in on_blind.items():
        robust_results[f"{name} (blind pairs)"] = evaluate(runs, grades, "condensed")
    names = [f"{mode}: {c}" for mode in ("query", "profile") for c in MAIN]
    blind_cut = cut & blind_set
    missing = {
        name: len(want - set(read_records(folder / V3_FILES[name])))
        for name, want in (("gemini", cut), ("groq", blind_cut), ("cowork", blind_cut))
    }
    open_items = [f"{n}: {m} cut pairs not re-judged on input v3" for n, m in missing.items() if m]

    return {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "commit": commit,
        "label_set": folder.name,
        "snapshot": pool["snapshot"],
        "corpus_sha256": pool["corpus_sha256"],
        "method": "LLM-judged (Gemini). No human relevance labels.",
        "labels_used": (
            "final: judge input v3 (section-aware) for the pairs whose description v2 cut, "
            "the existing labels for every other pair (identical input, same sha256)"
        ),
        "pairs": {
            "total": len(every),
            "pooled": len(pooled),
            "fills": pool.get("fills", []),
            "blind": len(blind),
            "cut": len(cut),
            "graded": {name: len(g) for name, g in labels.items()},
            "label_source_counts": {
                name: dict(Counter("llm" for _ in g)) for name, g in labels.items()
            },
            "grades": {
                name: dict(sorted(Counter(g.values()).items())) for name, g in labels.items()
            },
        },
        "input_fix": input_fix(folder, sets, cut),
        "metrics": {c: _clean(r) for c, r in primary.items()},
        "sensitivity_v2": sensitivity(primary["unjudged0"], baseline_v2),
        "rerank_choice": {
            "query": choose_rerank(primary["unjudged0"], "query"),
            "query (v2 labels)": choose_rerank(baseline_v2, "query"),
            "profile (digest)": choose_rerank(primary["unjudged0"], "profile"),
            "target_p95_ms": TARGET_P95_MS,
            "latency_source": LATENCY_SOURCE,
        },
        "agreement": {"blind": agreement_report(common, matched, facts_for(sets["final"]))},
        "agreement_pairs": len(common),
        "agreement_change": [
            kappa_change(common, a, b, matched, labels_v2)
            for a, b in (("gemini", "groq"), ("gemini", "cowork"), ("groq", "cowork"))
        ],
        "hash_matched": hash_matched,
        "agreement_before_fix": {
            "blind": agreement_report(common, labels_v2, facts_for(sets["v2"]))
        },
        "robustness": robustness(robust_results, "gemini (all pairs)", names),
        "subsets": subsets(
            runs,
            labels[PRIMARY],
            subset_drops(
                job_facts(folder.parents[1] / "snapshots" / pool["snapshot"] / "reduced"),
                pool["snapshot"],
            ),
        ),
        "pending": pending or ("; ".join(open_items) if open_items else None),
        "limitations": LIMITATIONS,
        "deferred": DEFERRED,
    }


def _ci(est: Mapping[str, Any] | None, signed: bool = False) -> str:
    if est is None:
        return "-"
    f = "{:+.3f}" if signed else "{:.3f}"
    return f"{f.format(est['mean'])} [{f.format(est['ci_low'])}, {f.format(est['ci_high'])}]"


def agreement_lines(agreement: Mapping[str, Any]) -> list[str]:
    """The agreement tables: per pair of judges, n, weighted kappa with its bootstrap CI,
    exact and within-one agreement, the confusion matrix and the disagreement themes
    with up to three example pairs each."""
    out: list[str] = []
    add = out.append
    titles = {
        "blind": "Blind pairs",
        "pooled_gemini_vs_cowork": "Pooled pairs, Gemini vs Claude Cowork",
    }
    for key, a in agreement.items():
        add(f"### {titles.get(key, key)} ({a['pairs']} pairs; graded {a['graded']})")
        add("")
        add("n is the number of pairs both judges graded.")
        add("")
        add("| Judges | n | weighted kappa [95% CI] | exact | within one | mean a - b |")
        add("|---|---:|---|---:|---:|---:|")
        for x in a["pairwise"]:
            k = "-" if x["weighted_kappa"] is None else f"{x['weighted_kappa']:.3f}"
            ci = x.get("weighted_kappa_ci95")
            if ci:
                k += f" [{ci[0]:.3f}, {ci[1]:.3f}]"
            add(
                f"| {x['a']} vs {x['b']} | {x['n']} | {k} | {x['exact']:.1%} | "
                f"{x['within_one']:.1%} | {x['mean_diff_a_minus_b']:+.2f} |"
            )
        add("")
        for x in a["pairwise"]:
            add(f"#### {x['a']} vs {x['b']}")
            add("")
            add(f"Confusion (rows {x['a']}, columns {x['b']}):")
            add("")
            add("| | 0 | 1 | 2 | 3 |")
            add("|---|---:|---:|---:|---:|")
            for g, row in enumerate(x["confusion_rows_a_cols_b"]):
                add(f"| **{g}** | " + " | ".join(str(c) for c in row) + " |")
            add("")
            cells = ", ".join(
                f"{c['a']}/{c['b']} x{c['pairs']}" for c in x["most_common_disagreements"]
            )
            add(f"Most common disagreements ({x['a']}/{x['b']}): {cells or '-'}.")
            add("")
            add(
                "Themes, tagged from the lower grader's reason and the posting's facts "
                "(a disagreement can carry several or none):"
            )
            add("")
            for t, v in x["themes"].items():
                add(
                    f"- **{t}**: {v['disagreements']} ({v['share']:.0%}); {x['a']} higher "
                    f"{v['a_higher']}, {x['b']} higher {v['b_higher']}"
                )
                for e in v.get("examples", []):
                    reason = " ".join(str(e["lower_reason"]).split())[:240]
                    add(
                        f"  - `{e['pair_id']}`: {x['a']} {e[x['a']]}, {x['b']} {e[x['b']]}; "
                        f'{e["lower"]} (lower): "{reason}"'
                    )
            add("")
        if "majority" in a:
            add(f"3-judge majority (median of three): {a['majority']}")
            add("")
    return out


def markdown(r: Mapping[str, Any], commands: list[str]) -> str:
    out: list[str] = []
    add = out.append
    add(f"# Phase 4 evaluation report: {r['label_set']} at {r['commit']}")
    add("")
    add(
        f"**{r['method']}** Generated {r['generated_at']}. Snapshot `{r['snapshot']}` "
        f"(corpus sha256 `{r['corpus_sha256'][:16]}…`)."
    )
    add("")
    p = r["pairs"]
    add("## Labels")
    add("")
    add(
        f"{p['total']} (profile, job) pairs: {p['pooled']} pooled, plus "
        + ", ".join(f"{f['added']} added by `{f['tag']}`" for f in p["fills"])
        + f". The blind set is {p['blind']} of the pooled pairs."
    )
    add("")
    add("| Judge | Pairs graded | label_source | Grades 0 / 1 / 2 / 3 |")
    add("|---|---:|---|---|")
    for name, n in p["graded"].items():
        g = p["grades"][name]
        dist = " / ".join(str(g.get(k, g.get(str(k), 0))) for k in range(4))
        add(f"| {JUDGE_NAMES[name]} | {n} | llm | {dist} |")
    add("")
    add("Primary labels: Gemini. No pair has a human label.")
    add("")
    add(
        f"Labels used: {r['labels_used']}. Claude Cowork is a third judge on the 120 blind "
        "pairs only (its other batches were cancelled, owner decision 2026-11-27)."
    )
    add("")
    fx = r["input_fix"]
    cc = fx["controlled_check"]
    add("## The input fix (judge input v2 -> v3)")
    add("")
    add(
        f"Input v2 sent each description's first ~1,400 characters; {fx['cut_pairs']} of "
        f"{p['total']} pairs were cut, often before the experience requirement. Input v3 "
        "trims by section (requirements and experience/seniority first, boilerplate last, "
        "cap 3,200 characters) and is identical to v2 for every uncut pair (same sha256)."
    )
    add("")
    add(
        f"- Controlled check (Gemini, same settings, cache off): cut pairs "
        f"{cc['cut']['changed']}/{cc['cut']['n']} grades changed "
        f"({cc['cut']['rate']:.1%}; {cc['cut']['down']} down, {cc['cut']['up']} up), "
        f"control {cc['control']['changed']}/{cc['control']['n']} "
        f"({cc['control']['rate']:.1%}): effect {cc['effect_points']:+.1f} points."
    )
    nz = fx["noise_rerun"]
    add(
        f"- Long-text noise: {nz['changed']} of {nz['pairs']} cut pairs changed grade when "
        "Gemini judged the same v3 input a second time."
    )
    ac = fx["all_cut"]
    if ac["rate"] is not None:
        add(
            f"- All cut pairs re-judged ({fx['cut_rejudged']} of {fx['cut_pairs']}): "
            f"{ac['changed']} changed ({ac['rate']:.1%}; {ac['down']} down, {ac['up']} up); "
            f"transitions {ac['transitions']}."
        )
    add("")
    km = r["metrics"]["unjudged0"]
    kv, kc = km["variants"], km["comparisons"]
    chosen = r["rerank_choice"]["query"]["chosen"]
    step = {name: label for label, name in STEPS}
    add("## Key results (query mode, LLM-judged (Gemini))")
    add("")
    for v in ("bm25", "fused", "rescore", chosen):
        add(f"- `{v}` ({step[v]}): NDCG@10 {_ci(kv[f'query:{v}']['ndcg10'])}")
    for name in ("hybrid vs keyword", "+personalisation vs hybrid", f"{step[chosen]} vs keyword"):
        d = kc.get(f"query: {name}", {}).get("ndcg10")
        if d:
            add(f"- {name}: {_ci(d, True)}, p={d['p_value']:.3f} ({d['verdict']})")
    for x in r["agreement"]["blind"]["pairwise"]:
        if x["weighted_kappa"] is not None:
            add(
                f"- Blind pairs, {x['a']} vs {x['b']}: weighted kappa {x['weighted_kappa']:.2f} "
                f"(n={x['n']})"
            )
    add("")
    for conv, title in (("unjudged0", "primary"), ("condensed", "check: condensed lists")):
        m = r["metrics"][conv]
        add(f"## Metrics, LLM-judged (Gemini), {title}")
        add("")
        add(
            "Mean over 25 profiles, 95% percentile bootstrap CI over profiles. judged@10 is "
            "the share of a variant's top 10 that Gemini graded."
        )
        add("")
        add("| Variant | NDCG@10 | MRR | Recall@30 | judged@10 |")
        add("|---|---|---|---|---|")
        for v, row in m["variants"].items():
            add(
                f"| `{v}` | {_ci(row['ndcg10'])} | {_ci(row['mrr'])} | {_ci(row['recall30'])} "
                f"| {row['judged10']['mean']:.2f} |"
            )
        add("")
    m = r["metrics"]["unjudged0"]
    add("## Comparisons, LLM-judged (Gemini)")
    add("")
    add(
        "Paired over profiles: mean difference (a - b), bootstrap 95% CI, two-sided "
        "sign-flip permutation p. Verdict: better / worse when the CI excludes 0."
    )
    add("")
    add("| Comparison | " + " | ".join(METRIC_NAMES[x] for x in METRICS) + " |")
    add("|---|" + "---|" * len(METRICS))
    for name, row in m["comparisons"].items():
        cells = []
        for metric in METRICS:
            d = row.get(metric)
            cells.append(
                "-" if d is None else f"{_ci(d, True)} p={d['p_value']:.3f} {d['verdict']}"
            )
        add(f"| {name} | " + " | ".join(cells) + " |")
    add("")
    rc = r["rerank_choice"]
    add("## Subsets: source snippets and stale postings (query mode)")
    add("")
    add(
        "The same rankings with some jobs removed (later jobs move up), scored with "
        "condensed lists, LLM-judged (Gemini). Mean NDCG@10 [95% CI]."
    )
    add("")
    subs = r["subsets"]
    steps = list(next(iter(subs.values()))["ndcg10"])
    add("| Variant | " + " | ".join(subs) + " |")
    add("|---|" + "---|" * len(subs))
    for v in steps:
        add(f"| `{v}` | " + " | ".join(_ci(s["ndcg10"].get(v)) for s in subs.values()) + " |")
    names = list(next(iter(subs.values()))["comparisons"])
    for name in names:
        cells = []
        for s in subs.values():
            d = s["comparisons"].get(name)
            cells.append("-" if d is None else f"{_ci(d, True)} {d['verdict']}")
        add(f"| {name.removeprefix('query: ')} | " + " | ".join(cells) + " |")
    add("")
    for name, s in subs.items():
        add(
            f"- {name}: {s['description']}; {s['dropped_jobs']} jobs removed, "
            f"{s['labelled_pairs']} labelled pairs left."
        )
    add("")
    add("## ADR 0003: the interactive rerank setting")
    add("")
    add(
        "Rule (paired form, owner decision 2026-11-27): eligible = within 0.01 NDCG@10 of "
        "the best setting, or a paired CI of the difference to the best that includes 0; "
        "choose the eligible setting with the lowest single-search p95."
    )
    add("")
    for label, choice in (
        ("Interactive search (query mode)", rc["query"]),
        ("Digest (profile mode, for reference)", rc["profile (digest)"]),
    ):
        if label.startswith("Interactive"):
            add(
                f"**{label}**: best `{choice['best']}`; eligible {choice['eligible']}; "
                f"chosen **`{choice['chosen']}`**, p95 {choice['chosen_p95_ms']:.0f} ms, "
                f"{'meets' if choice['meets_300ms'] else 'misses'} the 300 ms target."
            )
        else:
            d = m["comparisons"]["profile: +rerank 30@256 vs +personalisation"]["ndcg10"]
            add(
                f'**{label}**: ADR 0003 keeps the digest at 30@256 "unless that table shows '
                'it does not help" (nobody waits for it). 30@256 vs no rerank, profile '
                f"mode: {_ci(d, True)} ({d['verdict']}); the interactive rule would pick "
                f"`{choice['chosen']}`, which does not apply to the digest."
            )
        add("")
        add("| Setting | NDCG@10 | difference to best | p50 / p95 ms |")
        add("|---|---|---|---|")
        for name, est in choice["ndcg10"].items():
            d = choice["difference_to_best"].get(name)
            lat = choice["latency_ms"][name]
            add(
                f"| `{name}` | {_ci(est)} | {_ci(d, True) if d else '(best)'} | "
                f"{lat['p50']:.0f} / {lat['p95']:.0f} |"
            )
        add("")
    add(f"Latency: {rc['latency_source']}.")
    add("")
    add("## Agreement between the LLM judges")
    add("")
    hm = r["hash_matched"]
    add(
        "After the input fix (final labels). On the blind pairs a grade is used only if "
        "its judge input has the same sha256 as Gemini's final input for that pair: "
        + ", ".join(f"{n} {v['used']} of {v['blind_graded']}" for n, v in hm.items())
        + "."
    )
    add("")
    out.extend(agreement_lines(r["agreement"]))
    add("### Before vs after the input fix, on identical pairs")
    add("")
    add(
        f"Both columns use the same {r['agreement_pairs']} blind pairs (those where every "
        "judge has a final grade from hash-identical input); 'before' uses each judge's "
        "v2-era grade for those pairs (Claude Cowork's mostly from the labelling tool)."
    )
    add("")
    add(
        "| Judges | n | weighted kappa [95% CI], before | after | change (after - before) "
        "[95% paired bootstrap CI] | verdict |"
    )
    add("|---|---:|---|---|---|---|")
    change = {(c["a"], c["b"]): c for c in r["agreement_change"]}
    after = {(x["a"], x["b"]): x for x in r["agreement"]["blind"]["pairwise"]}
    for x in r["agreement_before_fix"]["blind"]["pairwise"]:
        y = after.get((x["a"], x["b"]))

        def kci(z: Mapping[str, Any] | None) -> str:
            if not z or z["weighted_kappa"] is None:
                return "-"
            ci = z.get("weighted_kappa_ci95") or [float("nan")] * 2
            return f"{z['weighted_kappa']:.3f} [{ci[0]:.3f}, {ci[1]:.3f}]"

        c = change.get((x["a"], x["b"]))
        if c and c["delta"] is not None:
            d = f"{c['delta']:+.3f} [{c['ci95'][0]:+.3f}, {c['ci95'][1]:+.3f}] (n={c['n']})"
            v = c["verdict"]
        else:
            d, v = "-", "-"
        add(f"| {x['a']} vs {x['b']} | {x['n']} | {kci(x)} | {kci(y)} | {d} | {v} |")
    add("")
    add(
        "The change is a paired bootstrap over the same pairs (2,000 resamples): "
        "agreement is said to have improved only for a judge pair whose CI excludes 0."
    )
    add("")
    sv = r["sensitivity_v2"]
    add("## Sensitivity: final labels vs v2 labels (Gemini, NDCG@10)")
    add("")
    add("| Variant | final | v2 | delta |")
    add("|---|---:|---:|---:|")
    for v, row in sv["ndcg10"].items():
        add(f"| `{v}` | {row['final']:.3f} | {row['v2']:.3f} | {row['delta']:+.3f} |")
    add("")
    add("| Comparison | final | v2 | same verdict |")
    add("|---|---|---|---|")
    for name, c in sv["comparisons"].items():
        add(
            f"| {name} | {_ci(c['final'], True)} {c['final']['verdict']} | "
            f"{_ci(c['v2'], True)} {c['v2']['verdict']} | {'yes' if c['same_verdict'] else 'NO'} |"
        )
    v2c = r["rerank_choice"].get("query (v2 labels)")
    if v2c:
        add("")
        add(f"ADR 0003 choice under v2 labels: `{v2c['chosen']}`.")
    add("")
    rb = r["robustness"]
    add("## Robustness: do the conclusions hold under every judge?")
    add("")
    add(
        "NDCG@10 difference (a - b) and 95% CI per judge. The reference is Gemini on all "
        "pairs; the blind columns use condensed lists over the 120 blind pairs (about 5 per "
        "profile), so they are much noisier. holds = same verdict as the reference; weaker "
        "= the reference's difference is not clear under this judge; differs = this judge "
        "finds a difference the reference does not; reverses = opposite verdicts."
    )
    add("")
    judges = list(next(iter(rb["comparisons"].values())).keys())
    add("| Comparison | " + " | ".join(judges) + " |")
    add("|---|" + "---|" * len(judges))
    for name, row in rb["comparisons"].items():
        cells = []
        for j in judges:
            c = row[j]
            cells.append(
                "-" if c is None else f"{_ci(c, True)} {c['verdict']} ({c['vs_reference']})"
            )
        add(f"| {name} | " + " | ".join(cells) + " |")
    add("")
    add(
        "Rerank setting each judge's labels choose (query mode, same rule): "
        + ", ".join(f"{j}: `{c}`" for j, c in rb["rerank_choice"].items())
        + "."
    )
    add("")
    if r.get("pending"):
        add(f"**Pending:** {r['pending']}.")
        add("")
    add("## Limitations")
    add("")
    for item in r["limitations"]:
        add(f"- {item}")
    add("")
    add("## Not done in Phase 4 (deferred by the owner, 2026-11-27)")
    add("")
    for item in r["deferred"]:
        add(f"- {item}")
    add("")
    add("## Commands")
    add("")
    add("```")
    out.extend(commands)
    add("```")
    return "\n".join(out) + "\n"
