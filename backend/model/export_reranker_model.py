"""Build-time only (Docker `model` stage): export the ms-marco-MiniLM-L6-v2 cross-encoder
to fp32 ONNX and check that the runtime reranker (a) reproduces Sentence Transformers'
PyTorch scores and (b) gives a pair the same score whatever else is in its batch.

Not int8: dynamic int8 scores depended on batch neighbours (up to 0.46 logit) and static
int8 leaked padding; see app/ml/reranker.py and docs/retrieval.md.

    python model/export_reranker_model.py OUT_DIR

The model revision is pinned so every build ranks identically.
"""

import shutil
import sys
import tempfile
from pathlib import Path

import numpy as np
import torch
from sentence_transformers import CrossEncoder

MODEL = "cross-encoder/ms-marco-MiniLM-L6-v2"
REVISION = "233902d25c440f23af6f7d6e94d2946bac0bee0a"
MODEL_FILE = "model.onnx"
# Largest allowed |logit difference|: runtime vs PyTorch, and batched vs one pair alone.
MAX_DELTA = 0.01

CHECK = [
    (
        "remote machine learning engineer python",
        [
            "Machine Learning Engineer. Build ranking models in Python and PyTorch. Remote.",
            "Senior Accountant. Month-end close, IFRS, NetSuite. Office in Mumbai.",
            "Data Engineer. Spark and Airflow pipelines; some Python. Hybrid, Bengaluru.",
            "Sales Development Representative for our EMEA region.",
        ],
    ),
    (
        "frontend developer react typescript bengaluru",
        [
            "Frontend Engineer, React and TypeScript, Bengaluru office.",
            "Backend Engineer, Go and PostgreSQL, Berlin.",
            "Product Designer with Figma and design systems.",
            "Full-stack developer: Next.js, Node, TypeScript. Remote India.",
        ],
    ),
    (
        "entry level data analyst sql",
        [
            "Junior Data Analyst: SQL, Excel, dashboards in Looker.",
            "Staff Software Engineer, distributed systems, 10+ years.",
            "Analytics Engineer: dbt, SQL, Snowflake.",
            "Customer Support Specialist, weekend shifts.",
        ],
    ),
]


def main(out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        onnx_model = CrossEncoder(
            MODEL,
            revision=REVISION,
            backend="onnx",
            device="cpu",
            model_kwargs={"file_name": "onnx/model.onnx"},
        )
        onnx_model.save_pretrained(str(work))
        produced = sorted(str(p.relative_to(work)) for p in work.rglob("*.onnx"))
        print("onnx files produced:", produced)
        candidates = list(work.rglob(MODEL_FILE))
        if len(candidates) != 1:
            raise SystemExit(f"expected one {MODEL_FILE}, found {produced}")
        shutil.copy(candidates[0], out_dir / MODEL_FILE)
        shutil.copy(next(work.rglob("tokenizer.json")), out_dir / "tokenizer.json")

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from app.ml.reranker import OnnxReranker

    # Raw logits from the PyTorch model (no activation), what the runtime returns.
    reference = CrossEncoder(MODEL, revision=REVISION, device="cpu")
    runtime = OnnxReranker(out_dir, MODEL_FILE, batch_size=8)
    alone = OnnxReranker(out_dir, MODEL_FILE, batch_size=1)
    worst_ref = worst_batch = 0.0
    for query, passages in CHECK:
        ref = reference.predict(
            [(query, p) for p in passages], activation_fn=torch.nn.Identity()
        ).tolist()
        # Padding is exercised: the passages differ in length, and a long unrelated one is
        # added so every batch is padded to it.
        batch = [*passages, "Unrelated filler text about something else entirely. " * 20]
        got = runtime.score(query, batch, 512)[: len(passages)]
        single = alone.score(query, passages, 512)
        print("query:", query, "| torch:", np.round(ref, 4), "| onnx:", np.round(got, 4))
        if int(np.argmax(ref)) != int(np.argmax(got)):
            raise SystemExit(f"runtime picks a different best passage for {query!r}")
        worst_ref = max(worst_ref, *(abs(a - b) for a, b in zip(ref, got, strict=True)))
        worst_batch = max(worst_batch, *(abs(a - b) for a, b in zip(got, single, strict=True)))
    print(f"reranker parity: max |logit diff| vs torch {worst_ref:.6f}")
    print(f"reranker batch independence: max |logit diff| batched vs alone {worst_batch:.6f}")
    if worst_ref > MAX_DELTA or worst_batch > MAX_DELTA:
        raise SystemExit(f"reranker check failed (limit {MAX_DELTA})")
    print(f"wrote {out_dir / MODEL_FILE} ({(out_dir / MODEL_FILE).stat().st_size} bytes)")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
