"""The Phase 4 report: eval/reports/<date>-<commit>.json and .md (brief item 9).

Everything is computed from committed files: the set's runs.jsonl (every variant's
ranking on the frozen snapshot), plan.json (the blind pairs), export/pairs_index.jsonl
and the judges' label files. Every metric is LLM-judged; the primary labels are Gemini's.
There are no human relevance labels (owner decision 2026-11-27).
"""

import json
from collections import Counter
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from app.eval.agreement import JUDGES, Facts, agreement_report, majority
from app.eval.evaluate import (
    LATENCY_SOURCE,
    METRICS,
    STEPS,
    TARGET_P95_MS,
    choose_rerank,
    evaluate,
    load_runs,
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


def _clean(result: Mapping[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in result.items() if not k.startswith("_")}


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
    runs = load_runs(folder / "runs.jsonl")
    labels = load_labels(folder)
    reasons = {
        name: {
            r.pair_id: r.reason
            for r in (JudgeRecord.model_validate(x) for x in read_jsonl(folder / file))
        }
        for name, file in JUDGES.items()
    }
    facts = Facts(strata=strata, reasons=reasons)

    primary = {c: evaluate(runs, labels[PRIMARY], c) for c in ("unjudged0", "condensed")}
    on_blind = {
        name: {pid: g for pid, g in labels[name].items() if pid in blind_set} for name in JUDGES
    }
    on_blind["majority"] = majority(blind, {n: on_blind[n] for n in JUDGES})
    robust_results = {"gemini (all pairs)": primary["unjudged0"]}
    for name, grades in on_blind.items():
        robust_results[f"{name} (blind pairs)"] = evaluate(runs, grades, "condensed")
    cowork_all = {pid: g for pid, g in labels["cowork"].items() if pid in strata}
    complete = len(cowork_all) == len(every)
    if complete:
        robust_results["cowork (all pairs)"] = evaluate(runs, cowork_all, "unjudged0")
    names = [f"{mode}: {c}" for mode in ("query", "profile") for c in MAIN]

    return {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "commit": commit,
        "label_set": folder.name,
        "snapshot": pool["snapshot"],
        "corpus_sha256": pool["corpus_sha256"],
        "method": "LLM-judged (Gemini). No human relevance labels.",
        "pairs": {
            "total": len(every),
            "pooled": len(pooled),
            "fills": pool.get("fills", []),
            "blind": len(blind),
            "graded": {name: len(g) for name, g in labels.items()},
            "label_source_counts": {
                name: dict(Counter("llm" for _ in g)) for name, g in labels.items()
            },
            "grades": {
                name: dict(sorted(Counter(g.values()).items())) for name, g in labels.items()
            },
        },
        "metrics": {c: _clean(r) for c, r in primary.items()},
        "rerank_choice": {
            "query": choose_rerank(primary["unjudged0"], "query"),
            "profile (digest)": choose_rerank(primary["unjudged0"], "profile"),
            "target_p95_ms": TARGET_P95_MS,
            "latency_source": LATENCY_SOURCE,
        },
        "agreement": {
            "blind": agreement_report(blind, labels, facts),
            "pooled_gemini_vs_cowork": agreement_report(
                pooled, {k: labels[k] for k in ("gemini", "cowork")}, facts
            ),
        },
        "robustness": robustness(robust_results, "gemini (all pairs)", names),
        "pending": pending
        or (None if complete else "Claude Cowork on every pair: batches not imported yet"),
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
    out.extend(agreement_lines(r["agreement"]))
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
