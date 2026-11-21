"""Build-time only (Docker `model` stage): export the ms-marco-MiniLM-L6-v2 cross-encoder
to ONNX, quantise it to int8, and check the runtime reranker reproduces Sentence
Transformers' fp32 scores.

    python model/export_reranker_model.py OUT_DIR

The model revision is pinned so every build ranks identically.
"""

import shutil
import sys
import tempfile
from pathlib import Path

import numpy as np
import torch
from sentence_transformers import CrossEncoder, export_dynamic_quantized_onnx_model

MODEL = "cross-encoder/ms-marco-MiniLM-L6-v2"
REVISION = "233902d25c440f23af6f7d6e94d2946bac0bee0a"
QUANTIZATION = "avx2"  # same preset as the embedding model; see docs/decisions/log.md
QUANTIZED_FILE = f"model_quint8_{QUANTIZATION}.onnx"
# Parity thresholds, int8 runtime vs fp32 reference, over the check pairs below:
# Pearson correlation of the logits, and the same best passage for every query.
MIN_CORRELATION = 0.98

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
        onnx_model = CrossEncoder(MODEL, revision=REVISION, backend="onnx", device="cpu")
        onnx_model.save_pretrained(str(work))
        export_dynamic_quantized_onnx_model(onnx_model, QUANTIZATION, str(work))
        produced = sorted(str(p.relative_to(work)) for p in work.rglob("*.onnx"))
        print("onnx files produced:", produced)
        candidates = list(work.rglob(QUANTIZED_FILE))
        if len(candidates) != 1:
            raise SystemExit(f"expected {QUANTIZED_FILE}, found {produced}")
        shutil.copy(candidates[0], out_dir / QUANTIZED_FILE)
        shutil.copy(next(work.rglob("tokenizer.json")), out_dir / "tokenizer.json")

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from app.ml.reranker import OnnxReranker

    # Raw logits from the fp32 model (no activation), the same quantity the runtime returns.
    reference = CrossEncoder(MODEL, revision=REVISION, device="cpu")
    runtime = OnnxReranker(out_dir, QUANTIZED_FILE)
    ref_all: list[float] = []
    run_all: list[float] = []
    for query, passages in CHECK:
        ref = reference.predict(
            [(query, p) for p in passages], activation_fn=torch.nn.Identity()
        ).tolist()
        got = runtime.score(query, passages)
        print("query:", query, "| fp32:", np.round(ref, 3), "| int8:", np.round(got, 3))
        if int(np.argmax(ref)) != int(np.argmax(got)):
            raise SystemExit(f"int8 runtime picks a different best passage for {query!r}")
        ref_all += ref
        run_all += got
    correlation = float(np.corrcoef(ref_all, run_all)[0, 1])
    print(f"reranker parity: pearson {correlation:.4f} over {len(ref_all)} pairs")
    if correlation < MIN_CORRELATION:
        raise SystemExit(f"int8 reranker diverges from reference (pearson {correlation:.4f})")
    print(f"wrote {out_dir / QUANTIZED_FILE} ({(out_dir / QUANTIZED_FILE).stat().st_size} bytes)")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
