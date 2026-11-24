"""Batch consistency of the bge-small embedder: int8 dynamic (current) vs fp32 ONNX.

Run in the Docker `model` stage image (torch + sentence-transformers + onnxruntime):
    docker run --rm -v <dir with cards.json>:/sp jobmatch-model:exp \
        python /sp/embedder_variants_experiment.py
cards.json: real job cards (app.ingest.embed.job_card), what ingest embeds.

For each variant: max (1 - cos) between a card embedded alone and inside length-sorted
batches of 8 (what ingest does) and inside one unsorted padded batch; agreement with the
Sentence Transformers PyTorch reference; throughput with onnxruntime default threads
and one thread; process peak RSS.
"""

import json
import resource
import time
from pathlib import Path

import numpy as np
import onnxruntime as ort
from sentence_transformers import SentenceTransformer, export_dynamic_quantized_onnx_model
from tokenizers import Tokenizer

MODEL = "BAAI/bge-small-en-v1.5"
REVISION = "5c38ec7c405ec4b44b94cc5a9bb96e735b38267a"
WORK = Path("/tmp/emb")
CARDS = json.load(open("/sp/cards.json"))[:60]  # sized to finish within 5 minutes


def log(*a: object) -> None:
    print(*a, flush=True)


st = SentenceTransformer(
    MODEL, revision=REVISION, backend="onnx", device="cpu",
    model_kwargs={"file_name": "onnx/model.onnx"},
)
st.save_pretrained(str(WORK))
export_dynamic_quantized_onnx_model(st, "avx2", str(WORK))
FP32 = next(WORK.rglob("model.onnx"))
INT8 = next(WORK.rglob("model_quint8_avx2.onnx"))
tokenizer = Tokenizer.from_file(str(next(WORK.rglob("tokenizer.json"))))
tokenizer.enable_truncation(512)


def session(path: Path, threads: int) -> ort.InferenceSession:
    o = ort.SessionOptions()
    o.intra_op_num_threads = threads
    o.inter_op_num_threads = 1
    o.enable_cpu_mem_arena = False
    o.add_session_config_entry("session.intra_op.allow_spinning", "0")
    return ort.InferenceSession(str(path), o, providers=["CPUExecutionProvider"])


def embed(sess: ort.InferenceSession, texts: list[str]) -> np.ndarray:
    names = {i.name for i in sess.get_inputs()}
    enc = tokenizer.encode_batch(texts)
    width = max(len(e.ids) for e in enc)
    pad = lambda rows: np.array([r + [0] * (width - len(r)) for r in rows], dtype=np.int64)  # noqa: E731
    feed = {"input_ids": pad([e.ids for e in enc]), "attention_mask": pad([e.attention_mask for e in enc])}
    if "token_type_ids" in names:
        feed["token_type_ids"] = pad([e.type_ids for e in enc])
    cls = sess.run(None, feed)[0][:, 0, :]
    return cls / np.linalg.norm(cls, axis=1, keepdims=True)


def batched(sess: ort.InferenceSession, texts: list[str], size: int, sort: bool) -> np.ndarray:
    order = sorted(range(len(texts)), key=lambda i: len(tokenizer.encode(texts[i]).ids)) if sort else list(range(len(texts)))
    out = np.zeros((len(texts), 384))
    for s in range(0, len(order), size):
        chunk = order[s:s + size]
        out[chunk] = embed(sess, [texts[i] for i in chunk])
    return out


log("reference")
reference = SentenceTransformer(MODEL, revision=REVISION, device="cpu").encode(CARDS, normalize_embeddings=True)
lengths = [len(tokenizer.encode(c).ids) for c in CARDS]
log(f"cards: {len(CARDS)}, tokens median {int(np.median(lengths))}, at 512: {sum(x >= 512 for x in lengths)}")

results = {}
for name, path in (("int8 dynamic (current)", INT8), ("fp32", FP32)):
    sess = session(path, 0)
    alone = np.vstack([embed(sess, [c]) for c in CARDS])
    sorted8 = batched(sess, CARDS, 8, sort=True)
    unsorted = batched(sess, CARDS, 32, sort=False)
    r = {
        "size_mb": round(path.stat().st_size / 1e6, 1),
        "max 1-cos, sorted batches of 8 vs alone": float(np.max(1 - (alone * sorted8).sum(1))),
        "max 1-cos, unsorted batches of 32 vs alone": float(np.max(1 - (alone * unsorted).sum(1))),
        "min cos vs torch fp32 (alone)": float(np.min((alone * reference).sum(1))),
        "mean cos vs torch fp32 (alone)": float(np.mean((alone * reference).sum(1))),
    }
    for threads in (0, 1):
        s = session(path, threads)
        sample = CARDS if threads == 0 else CARDS[:16]
        batched(s, CARDS[:8], 8, sort=True)  # warm-up
        t0, c0 = time.perf_counter(), time.process_time()
        batched(s, sample, 8, sort=True)
        wall, cpu = time.perf_counter() - t0, time.process_time() - c0
        r[f"cards/s, sorted batches of 8, threads={threads or 'default'}"] = round(len(sample) / wall, 2)
        r[f"CPU s per card, threads={threads or 'default'}"] = round(cpu / len(sample), 3)
        log(f"  {name}: timed threads={threads or 'default'}")
    r["process peak RSS MiB so far"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss // 1024
    results[name] = r
    log(name, json.dumps(r))
json.dump(results, open("/sp/embedder_variants.json", "w"), indent=1)
