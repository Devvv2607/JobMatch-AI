"""ms-marco-MiniLM-L6-v2 cross-encoder as an int8 ONNX model, run with onnxruntime and
tokenizers (no PyTorch). Loaded only by the API process, never by the worker.

The model reads (query, passage) pairs and returns one relevance logit per pair (higher
is more relevant). The export and the parity check against Sentence Transformers' fp32
CrossEncoder are in model/export_reranker_model.py.
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
        self._tokenizer.enable_truncation(
            min(max_tokens, MODEL_MAX_TOKENS), strategy="only_second"
        )
        self._tokenizer.enable_padding()
        options = ort.SessionOptions()
        options.intra_op_num_threads = threads
        options.inter_op_num_threads = 1
        options.enable_cpu_mem_arena = False
        self._session = ort.InferenceSession(
            str(model_dir / model_file), options, providers=["CPUExecutionProvider"]
        )
        self._inputs = {i.name for i in self._session.get_inputs()}

    def score(self, query: str, passages: list[str]) -> list[float]:
        """One logit per passage, in input order."""
        if not passages:
            return []
        encodings = self._tokenizer.encode_batch([(query, p) for p in passages])
        feed = {
            "input_ids": np.array([e.ids for e in encodings], dtype=np.int64),
            "attention_mask": np.array([e.attention_mask for e in encodings], dtype=np.int64),
        }
        if "token_type_ids" in self._inputs:
            feed["token_type_ids"] = np.array([e.type_ids for e in encodings], dtype=np.int64)
        logits = self._session.run(None, feed)[0]  # (batch, 1)
        scores: list[float] = np.asarray(logits, dtype=np.float64).reshape(len(passages)).tolist()
        return scores
