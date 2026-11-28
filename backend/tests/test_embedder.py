"""The real int8 model. It is baked into the Docker image, so these run there (and in
`make test`); on a host without the model they are skipped, never faked."""

import math
from pathlib import Path

import pytest

from app.core.config import get_settings

settings = get_settings()
MODEL_DIR = Path(settings.embedding_model_dir)
pytestmark = [
    pytest.mark.slow,
    pytest.mark.skipif(
        not (MODEL_DIR / settings.embedding_model_file).exists(),
        reason=f"embedding model not present at {MODEL_DIR}",
    ),
]


@pytest.fixture(scope="module")
def embedder():  # type: ignore[no-untyped-def]
    from app.ml.embedder import OnnxEmbedder

    return OnnxEmbedder(MODEL_DIR, settings.embedding_model_file)


def cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True))


def test_embeddings_are_384_dimensional_and_normalised(embedder) -> None:  # type: ignore[no-untyped-def]
    vectors = embedder.embed(["Senior Python engineer", "Pastry chef"])
    assert [len(v) for v in vectors] == [384, 384]
    assert all(math.isclose(math.sqrt(sum(x * x for x in v)), 1.0, rel_tol=1e-4) for v in vectors)
    assert embedder.embed([]) == []


def test_related_texts_are_closer_than_unrelated(embedder) -> None:  # type: ignore[no-untyped-def]
    backend, python_job, chef = embedder.embed(
        [
            "Backend engineer: Python, FastAPI, PostgreSQL, Kubernetes.",
            "We are hiring a Python developer to build REST APIs on Postgres.",
            "Head chef for a busy Italian restaurant, pasta and desserts.",
        ]
    )
    assert cosine(backend, python_job) > cosine(backend, chef) + 0.1


def test_long_texts_are_truncated_not_rejected(embedder) -> None:  # type: ignore[no-untyped-def]
    (vector,) = embedder.embed(["word " * 5000])
    assert len(vector) == 384


def test_query_embedding_uses_the_retrieval_instruction(embedder) -> None:  # type: ignore[no-untyped-def]
    query = embedder.embed_query("python backend jobs")
    plain = embedder.embed(["python backend jobs"])[0]
    assert len(query) == 384
    assert query != plain
