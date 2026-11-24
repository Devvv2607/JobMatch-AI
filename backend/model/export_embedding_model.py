"""Build-time only (Docker `model` stage): export bge-small-en-v1.5 to fp32 ONNX and check
that the runtime embedder (a) reproduces Sentence Transformers' PyTorch embeddings and
(b) embeds a text the same alone and inside a padded batch.

    python model/export_embedding_model.py OUT_DIR

Not int8: dynamic int8 vectors depended on batch neighbours (max 1 - cos 0.0079 on real
job cards, 2026-11-24); see app/ml/embedder.py. The model revision is pinned so every
build embeds identically.
"""

import shutil
import sys
import tempfile
from pathlib import Path

import numpy as np
from sentence_transformers import SentenceTransformer

MODEL = "BAAI/bge-small-en-v1.5"
REVISION = "5c38ec7c405ec4b44b94cc5a9bb96e735b38267a"
MODEL_FILE = "model.onnx"
# Per text: cosine to the PyTorch reference at least this, and 1 - cosine between the
# text alone and in a padded batch at most MAX_BATCH_DRIFT.
MIN_PARITY = 0.9999
MAX_BATCH_DRIFT = 0.001

CHECK_SENTENCES = [
    "Senior Python engineer, Bengaluru. FastAPI, PostgreSQL, Kubernetes.",
    "We are hiring a machine learning engineer to build retrieval and ranking systems.",
    "Remote (APAC). Product designer with Figma and design-system experience.",
    "Staff data engineer: Spark, Airflow, dbt, Snowflake. Hybrid in Mumbai.",
]
# Forces padding: every check sentence shares a batch with a 512-token text.
FILLER = "Unrelated filler text about something else entirely. " * 120


def main(out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        onnx_model = SentenceTransformer(
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
    from app.ml.embedder import OnnxEmbedder

    reference = SentenceTransformer(MODEL, revision=REVISION, device="cpu").encode(
        CHECK_SENTENCES, normalize_embeddings=True
    )
    embedder = OnnxEmbedder(out_dir, MODEL_FILE)
    batched = np.array(embedder.embed([*CHECK_SENTENCES, FILLER]))[: len(CHECK_SENTENCES)]
    alone = np.array([embedder.embed([s])[0] for s in CHECK_SENTENCES])
    parity = (reference * alone).sum(axis=1)
    drift = 1 - (alone * batched).sum(axis=1)
    print("parity cosine per sentence:", [round(float(x), 6) for x in parity])
    print(f"embedder batch independence: max 1-cos batched vs alone {float(drift.max()):.2e}")
    if float(parity.min()) < MIN_PARITY:
        raise SystemExit(f"runtime diverges from reference (min cos {parity.min():.6f})")
    if float(drift.max()) > MAX_BATCH_DRIFT:
        raise SystemExit(f"embedding depends on the batch (max 1-cos {drift.max():.2e})")
    print(f"wrote {out_dir / MODEL_FILE} ({(out_dir / MODEL_FILE).stat().st_size} bytes)")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
