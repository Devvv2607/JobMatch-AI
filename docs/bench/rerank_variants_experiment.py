"""Batch dependence of the cross-encoder: fp32 vs int8 dynamic vs int8 static, scored one
pair at a time, as one padded batch, and as length-sorted batches. Run in the model stage
image (torch + onnxruntime.quantization). Real job passages from /sp/passages.json."""

import json
import statistics
import time
from pathlib import Path

import numpy as np
import onnxruntime as ort
import torch
from onnxruntime.quantization import (
    CalibrationDataReader,
    CalibrationMethod,
    QuantFormat,
    QuantType,
    quantize_static,
)
from onnxruntime.quantization.shape_inference import quant_pre_process
from sentence_transformers import CrossEncoder, export_dynamic_quantized_onnx_model
from tokenizers import Tokenizer

MODEL = "cross-encoder/ms-marco-MiniLM-L6-v2"
REVISION = "233902d25c440f23af6f7d6e94d2946bac0bee0a"
WORK = Path("/tmp/exp")
PASSAGES = json.load(open("/sp/passages.json"))
TEST, CALIB = PASSAGES[:150], PASSAGES[150:]
QUERIES = [
    "senior python backend engineer", "data engineer spark airflow", "frontend react typescript",
    "machine learning engineer", "devops kubernetes terraform", "product designer figma",
    "site reliability engineer", "android developer kotlin", "security engineer", "data scientist",
]
CALIB_QUERIES = ["golang distributed systems", "technical writer", "ios engineer swift",
                 "analytics engineer dbt", "customer support specialist", "engineering manager"]


def log(*a): print(*a, flush=True)


# --- models ---------------------------------------------------------------------------
ce = CrossEncoder(MODEL, revision=REVISION, backend="onnx", device="cpu")
ce.save_pretrained(str(WORK))
fp32 = next(WORK.rglob("model.onnx"))
export_dynamic_quantized_onnx_model(ce, "avx2", str(WORK))
dyn = next(WORK.rglob("model_quint8_avx2.onnx"))
tok_file = next(WORK.rglob("tokenizer.json"))


def tokenizer(max_tokens):
    t = Tokenizer.from_file(str(tok_file))
    t.enable_truncation(max_tokens, strategy="only_second")
    return t


def feed_for(encodings, names):
    width = max(len(e.ids) for e in encodings)
    pad = lambda xs, v: [x + [v] * (width - len(x)) for x in xs]  # noqa: E731
    f = {"input_ids": np.array(pad([e.ids for e in encodings], 0), dtype=np.int64),
         "attention_mask": np.array(pad([e.attention_mask for e in encodings], 0), dtype=np.int64)}
    if "token_type_ids" in names:
        f["token_type_ids"] = np.array(pad([e.type_ids for e in encodings], 0), dtype=np.int64)
    return f


class Calib(CalibrationDataReader):
    def __init__(self, names):
        t = tokenizer(256)
        self.items = iter(feed_for([t.encode(q, p)], names)
                          for q in CALIB_QUERIES for p in CALIB[:25])

    def get_next(self):
        return next(self.items, None)


pre = WORK / "model_pre.onnx"
quant_pre_process(str(fp32), str(pre), skip_symbolic_shape=True)
names0 = {i.name for i in ort.InferenceSession(str(fp32), providers=["CPUExecutionProvider"]).get_inputs()}
static = {}
# Percentile calibration was OOM-killed in the 6 GB VM (histograms of every activation).
for per_channel in (True, False):
    label = "per-channel" if per_channel else "per-tensor"
    out = WORK / f"model_static_{label}.onnx"
    t0 = time.perf_counter()
    quantize_static(str(pre), str(out), Calib(names0), quant_format=QuantFormat.QDQ,
                    activation_type=QuantType.QUInt8, weight_type=QuantType.QInt8,
                    per_channel=per_channel, calibrate_method=CalibrationMethod.MinMax,
                    extra_options={"ActivationSymmetric": False})
    log(f"static MinMax {label}: {time.perf_counter()-t0:.0f}s, {out.stat().st_size} bytes")
    static[f"int8 static MinMax {label}"] = out

VARIANTS = {"fp32": fp32, "int8 dynamic (current)": dyn, **static}


def session(path):
    o = ort.SessionOptions()
    o.intra_op_num_threads = 0
    o.inter_op_num_threads = 1
    o.enable_cpu_mem_arena = False
    return ort.InferenceSession(str(path), o, providers=["CPUExecutionProvider"])


def score(sess, names, t, query, passages, mode, batch=8):
    encs = [t.encode(query, p) for p in passages]
    if mode == "single":
        return [float(sess.run(None, feed_for([e], names))[0].reshape(-1)[0]) for e in encs]
    if mode == "batch":
        return sess.run(None, feed_for(encs, names))[0].reshape(-1).astype(float).tolist()
    order = sorted(range(len(encs)), key=lambda i: len(encs[i].ids))  # length-sorted
    out = [0.0] * len(encs)
    for s in range(0, len(order), batch):
        chunk = order[s:s + batch]
        logits = sess.run(None, feed_for([encs[i] for i in chunk], names))[0].reshape(-1)
        for i, v in zip(chunk, logits):
            out[i] = float(v)
    return out


# --- (c) inputs --------------------------------------------------------------------------
s0 = session(dyn)
log("model inputs:", [(i.name, i.shape) for i in s0.get_inputs()])
e = tokenizer(128).encode(QUERIES[0], TEST[0])
log("sample pair: tokens", len(e.ids), "type_ids distinct", sorted(set(e.type_ids)),
    "mask sum", sum(e.attention_mask))
log("runtime feeds token_type_ids when the model has it:",
    "token_type_ids" in {i.name for i in s0.get_inputs()})

# --- reference: torch fp32, one pair at a time ----------------------------------------
ref_model = CrossEncoder(MODEL, revision=REVISION, device="cpu")
sets = {q: TEST[(i * 13) % 120:(i * 13) % 120 + 30] for i, q in enumerate(QUERIES)}
reference = {}
for tokens in (128, 256):
    ref_model.max_length = tokens
    for q, ps in sets.items():
        reference[(tokens, q)] = [float(ref_model.predict([(q, p)], activation_fn=torch.nn.Identity())[0]) for p in ps]

results = {}
for name, path in VARIANTS.items():
    sess = session(path)
    names = {i.name for i in sess.get_inputs()}
    r = {"size_mb": round(path.stat().st_size / 1e6, 1)}
    for tokens in (128, 256):
        t = tokenizer(tokens)
        deltas_batch, deltas_sorted, pearson, top10 = [], [], [], []
        for q, ps in sets.items():
            single = score(sess, names, t, q, ps, "single")
            deltas_batch += [abs(a - b) for a, b in zip(single, score(sess, names, t, q, ps, "batch"))]
            deltas_sorted += [abs(a - b) for a, b in zip(single, score(sess, names, t, q, ps, "sorted"))]
            ref = reference[(tokens, q)]
            pearson.append(float(np.corrcoef(ref, single)[0, 1]))
            top = lambda xs: set(sorted(range(len(xs)), key=lambda i: -xs[i])[:10])  # noqa: E731
            top10.append(len(top(ref) & top(single)) / 10)
        r[f"{tokens}t max|d| batch vs single"] = round(max(deltas_batch), 4)
        r[f"{tokens}t max|d| sorted-8 vs single"] = round(max(deltas_sorted), 4)
        r[f"{tokens}t pearson vs torch fp32 (min over queries)"] = round(min(pearson), 4)
        r[f"{tokens}t top10 overlap vs torch fp32 (mean)"] = round(statistics.mean(top10), 3)
    # Latency: 10 @ 128 and 30 @ 256, median over the 10 queries (after a warm-up).
    for top_n, tokens in ((10, 128), (30, 256)):
        t = tokenizer(tokens)
        score(sess, names, t, "warm", TEST[:4], "single")
        for mode in ("single", "batch", "sorted"):
            times = []
            for q, ps in sets.items():
                t0 = time.perf_counter()
                score(sess, names, t, q, ps[:top_n], mode)
                times.append((time.perf_counter() - t0) * 1000)
            r[f"ms {top_n}@{tokens} {mode}"] = round(statistics.median(times), 1)
    results[name] = r
    log(name, json.dumps(r))

json.dump(results, open("/sp/rerank_exp.json", "w"), indent=1)
log("done")
