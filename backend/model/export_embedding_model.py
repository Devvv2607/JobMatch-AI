"""Build-time only (Docker `model` stage): export bge-small-en-v1.5 to ONNX, quantise it
to int8, and check the runtime embedder reproduces Sentence Transformers' output.

    python scripts/export_embedding_model.py OUT_DIR

The model revision is pinned so every build embeds identically.
"""

import shutil
import sys
import tempfile
from pathlib import Path

import numpy as np
from sentence_transformers import SentenceTransformer, export_dynamic_quantized_onnx_model

MODEL = "BAAI/bge-small-en-v1.5"
REVISION = "5c38ec7c405ec4b44b94cc5a9bb96e735b38267a"
QUANTIZATION = "avx2"  # portable to any x86-64 host with AVX2; see docs/decisions/log.md
# The avx2 preset quantises to unsigned 8-bit (quint8); the file is named accordingly.
QUANTIZED_FILE = f"model_quint8_{QUANTIZATION}.onnx"
# Minimum cosine similarity between the int8 runtime's embedding and the fp32
# Sentence Transformers reference, per sentence.
MIN_PARITY = 0.98

CHECK_SENTENCES = [
    "Senior Python engineer, Bengaluru. FastAPI, PostgreSQL, Kubernetes.",
    "We are hiring a machine learning engineer to build retrieval and ranking systems.",
    "Remote (APAC). Product designer with Figma and design-system experience.",
    "Staff data engineer: Spark, Airflow, dbt, Snowflake. Hybrid in Mumbai.",
]


def main(out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        onnx_model = SentenceTransformer(MODEL, revision=REVISION, backend="onnx", device="cpu")
        onnx_model.save_pretrained(str(work))
        export_dynamic_quantized_onnx_model(onnx_model, QUANTIZATION, str(work))
        produced = sorted(str(p.relative_to(work)) for p in work.rglob("*.onnx"))
        print("onnx files produced:", produced)
        candidates = list(work.rglob(QUANTIZED_FILE))
        if len(candidates) != 1:
            raise SystemExit(f"expected {QUANTIZED_FILE}, found {produced}")
        quantized = candidates[0]
        shutil.copy(quantized, out_dir / QUANTIZED_FILE)
        shutil.copy(next(work.rglob("tokenizer.json")), out_dir / "tokenizer.json")

    # Parity: the runtime path (onnxruntime + tokenizers, CLS + L2) vs fp32 reference.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from app.ml.embedder import OnnxEmbedder

    reference = SentenceTransformer(MODEL, revision=REVISION, device="cpu").encode(
        CHECK_SENTENCES, normalize_embeddings=True
    )
    runtime = np.array(OnnxEmbedder(out_dir, QUANTIZED_FILE).embed(CHECK_SENTENCES))
    similarities = (reference * runtime).sum(axis=1)
    print("parity cosine per sentence:", [round(float(s), 4) for s in similarities])
    if float(similarities.min()) < MIN_PARITY:
        raise SystemExit(f"int8 runtime diverges from reference (min {similarities.min():.4f})")
    print(f"wrote {out_dir / QUANTIZED_FILE} ({(out_dir / QUANTIZED_FILE).stat().st_size} bytes)")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
