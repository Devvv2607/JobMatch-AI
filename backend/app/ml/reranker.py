"""ms-marco-MiniLM-L6-v2 cross-encoder as an int8 ONNX model, run with onnxruntime and
tokenizers (no PyTorch). Loaded only by the API process, never by the worker.

The model reads (query, passage) pairs and returns one relevance logit per pair (higher
is more relevant). The export and the parity check against Sentence Transformers' fp32
CrossEncoder are in model/export_reranker_model.py.

Pairs are scored one at a time, not as a padded batch. The model is dynamically
quantised: onnxruntime picks each activation's int8 scale from the whole input tensor,
so in a batch a job's score depended on the other passages and their padding. Measured
on 30 postings x 5 queries (2026-11-21): up to 0.49 logit apart, 12 of 50 top-10
positions changed; one at a time was also faster (1.38 s vs 1.60 s for 30 at 256
tokens), since nothing is padded to the longest passage.
"""

from pathlib import Path

import numpy as np
import onnxruntime as ort
from tokenizers import Tokenizer

MODEL_MAX_TOKENS = 512


class OnnxReranker:
    def __init__(
        self, model_dir: Path, model_file: str, max_tokens: int = MODEL_MAX_TOKENS, threads: int = 0
    ) -> None:
        self._tokenizer = Tokenizer.from_file(str(model_dir / "tokenizer.json"))
        # Only the passage is cut: the query is short and must survive whole.
        self._tokenizer.enable_truncation(min(max_tokens, MODEL_MAX_TOKENS), strategy="only_second")
        options = ort.SessionOptions()
        options.intra_op_num_threads = threads
        options.inter_op_num_threads = 1
        options.enable_cpu_mem_arena = False
        self._session = ort.InferenceSession(
            str(model_dir / model_file), options, providers=["CPUExecutionProvider"]
        )
        self._inputs = {i.name for i in self._session.get_inputs()}

    def score(self, query: str, passages: list[str]) -> list[float]:
        """One logit per passage, in input order. Each pair is scored on its own, so a
        passage's score never depends on what else is being scored."""
        return [self._score_one(query, p) for p in passages]

    def _score_one(self, query: str, passage: str) -> float:
        encoding = self._tokenizer.encode(query, passage)
        feed = {
            "input_ids": np.array([encoding.ids], dtype=np.int64),
            "attention_mask": np.array([encoding.attention_mask], dtype=np.int64),
        }
        if "token_type_ids" in self._inputs:
            feed["token_type_ids"] = np.array([encoding.type_ids], dtype=np.int64)
        logits = self._session.run(None, feed)[0]  # (1, 1)
        return float(np.asarray(logits, dtype=np.float64).reshape(-1)[0])
