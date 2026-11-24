"""bge-small-en-v1.5 as an int8 ONNX model, run with onnxruntime and tokenizers.

The model is exported and quantised with Sentence Transformers at image build time
(model/export_embedding_model.py), which also checks this runtime reproduces Sentence
Transformers' embeddings. At runtime there is no PyTorch, which keeps each process small.

bge-small uses the [CLS] token as the sentence embedding, then L2 normalisation
(1_Pooling/config.json: pooling_mode_cls_token; 2_Normalize).
"""

from pathlib import Path

import numpy as np
import onnxruntime as ort
from tokenizers import Tokenizer

MAX_TOKENS = 512
# bge's recommended prefix for short retrieval queries (not for passages).
QUERY_INSTRUCTION = "Represent this sentence for searching relevant passages: "


class OnnxEmbedder:
    def __init__(self, model_dir: Path, model_file: str, threads: int = 0) -> None:
        self._tokenizer = Tokenizer.from_file(str(model_dir / "tokenizer.json"))
        self._tokenizer.enable_truncation(MAX_TOKENS)
        self._tokenizer.enable_padding()
        options = ort.SessionOptions()
        options.intra_op_num_threads = threads
        options.inter_op_num_threads = 1
        # Without the arena, memory from a large batch is returned instead of being kept
        # for reuse; the resident size stays near the working set of the current batch.
        options.enable_cpu_mem_arena = False
        # Idle intra-op threads sleep instead of spin-waiting: with several sessions and
        # API workers on one machine, spinning threads burned the cores the others needed.
        options.add_session_config_entry("session.intra_op.allow_spinning", "0")
        self._session = ort.InferenceSession(
            str(model_dir / model_file), options, providers=["CPUExecutionProvider"]
        )
        self._inputs = {i.name for i in self._session.get_inputs()}

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        encodings = self._tokenizer.encode_batch(texts)
        feed = {
            "input_ids": np.array([e.ids for e in encodings], dtype=np.int64),
            "attention_mask": np.array([e.attention_mask for e in encodings], dtype=np.int64),
        }
        if "token_type_ids" in self._inputs:
            feed["token_type_ids"] = np.array([e.type_ids for e in encodings], dtype=np.int64)
        hidden = self._session.run(None, feed)[0]  # (batch, tokens, 384)
        cls = hidden[:, 0, :]
        norms = np.linalg.norm(cls, axis=1, keepdims=True)
        vectors: list[list[float]] = (cls / np.maximum(norms, 1e-12)).tolist()
        return vectors

    def embed_query(self, query: str) -> list[float]:
        return self.embed([QUERY_INSTRUCTION + query])[0]
