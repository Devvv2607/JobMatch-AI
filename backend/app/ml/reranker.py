"""ms-marco-MiniLM-L6-v2 cross-encoder as an fp32 ONNX model, run with onnxruntime and
tokenizers (no PyTorch). Loaded only by the API process, never by the worker.

The model reads (query, passage) pairs and returns one relevance logit per pair (higher
is more relevant). The export and the checks against Sentence Transformers' CrossEncoder
are in model/export_reranker_model.py.

Why fp32 and not int8 (measured 2026-11-23, 30 passages x 10 queries, 8 CPUs; details in
docs/retrieval.md): with dynamic int8 quantisation onnxruntime picks each activation's
scale from the whole input tensor, so a job's score depended on the other passages in
its batch (up to 0.46 logit). Static int8 leaked padding at 256 tokens (up to 1.19).
fp32 is exactly batch-independent, matches PyTorch, and was the fastest consistent
variant at 10 pairs x 128 tokens (161 ms batched vs 198 ms for int8 one pair at a time).

Pairs are tokenised, sorted by length and run in batches of `batch_size`, so short
passages are not padded to the longest one; scores come back in input order.
"""

from functools import cache
from pathlib import Path

import numpy as np
import onnxruntime as ort
from tokenizers import Encoding, Tokenizer

MODEL_MAX_TOKENS = 512


class OnnxReranker:
    def __init__(
        self,
        model_dir: Path,
        model_file: str,
        *,
        threads: int = 0,
        batch_size: int = 8,
    ) -> None:
        self._tokenizer_file = str(model_dir / "tokenizer.json")
        self._batch_size = batch_size
        options = ort.SessionOptions()
        options.intra_op_num_threads = threads
        options.inter_op_num_threads = 1
        options.enable_cpu_mem_arena = False
        # Idle intra-op threads sleep instead of spin-waiting: with several sessions and
        # API workers on one machine, spinning threads burned the cores the others needed.
        options.add_session_config_entry("session.intra_op.allow_spinning", "0")
        self._session = ort.InferenceSession(
            str(model_dir / model_file), options, providers=["CPUExecutionProvider"]
        )
        self._inputs = {i.name for i in self._session.get_inputs()}

    @cache  # noqa: B019 - one reranker per process; a tokenizer per token limit
    def _tokenizer(self, max_tokens: int) -> Tokenizer:
        tokenizer = Tokenizer.from_file(self._tokenizer_file)
        # Only the passage is cut: the query is short and must survive whole.
        tokenizer.enable_truncation(min(max_tokens, MODEL_MAX_TOKENS), strategy="only_second")
        return tokenizer

    def score(self, query: str, passages: list[str], max_tokens: int) -> list[float]:
        """One logit per passage, in input order, independent of the other passages."""
        if not passages:
            return []
        encodings = self._tokenizer(max_tokens).encode_batch([(query, p) for p in passages])
        order = sorted(range(len(encodings)), key=lambda i: len(encodings[i].ids))
        scores = [0.0] * len(encodings)
        for start in range(0, len(order), self._batch_size):
            chunk = order[start : start + self._batch_size]
            logits = self._run([encodings[i] for i in chunk])
            for i, logit in zip(chunk, logits, strict=True):
                scores[i] = logit
        return scores

    def _run(self, encodings: list[Encoding]) -> list[float]:
        width = max(len(e.ids) for e in encodings)

        def padded(rows: list[list[int]]) -> np.ndarray:
            return np.array([r + [0] * (width - len(r)) for r in rows], dtype=np.int64)

        feed = {
            "input_ids": padded([e.ids for e in encodings]),
            "attention_mask": padded([e.attention_mask for e in encodings]),
        }
        if "token_type_ids" in self._inputs:
            feed["token_type_ids"] = padded([e.type_ids for e in encodings])
        logits = self._session.run(None, feed)[0]  # (batch, 1)
        out: list[float] = np.asarray(logits, dtype=np.float64).reshape(-1).tolist()
        return out
