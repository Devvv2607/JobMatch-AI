"""The real fp32 cross-encoder. Baked into the Docker image, so these run there (and in
CI's image job); on a host without the model they are skipped, never faked."""

from pathlib import Path

import pytest

from app.core.config import get_settings
from app.retrieval.service import passage

settings = get_settings()
MODEL_DIR = Path(settings.reranker_model_dir)
pytestmark = [
    pytest.mark.slow,
    pytest.mark.skipif(
        not (MODEL_DIR / settings.reranker_model_file).exists(),
        reason=f"reranker model not present at {MODEL_DIR}",
    ),
]


@pytest.fixture(scope="module")
def reranker():  # type: ignore[no-untyped-def]
    from app.ml.reranker import OnnxReranker

    return OnnxReranker(MODEL_DIR, settings.reranker_model_file, batch_size=4)


def test_relevant_passages_score_higher_in_input_order(reranker) -> None:  # type: ignore[no-untyped-def]
    query = "senior python backend engineer"
    passages = [
        passage("Pastry Chef", [], "Croissants, laminated dough and sourdough."),
        passage(
            "Senior Backend Engineer",
            ["Python", "PostgreSQL"],
            "Build Python services and APIs on PostgreSQL.",
        ),
        passage("Sales Development Representative", [], "Outbound prospecting and quotas."),
    ]
    chef, engineer, sales = reranker.score(query, passages, 128)
    assert engineer > chef and engineer > sales
    assert engineer > 0 > chef


def test_a_score_does_not_depend_on_the_other_passages(reranker) -> None:  # type: ignore[no-untyped-def]
    """Regression: int8 dynamic quantisation moved scores by up to 0.46 logit with the
    batch's neighbours. Batches here mix lengths, so padding is exercised."""
    query = "data engineer spark"
    texts = [
        passage("Data Engineer", ["Spark"], "Batch pipelines in Spark and Airflow."),
        passage("Platform Engineer", ["Go"], "Kubernetes operators. " * 60),
        passage("Analyst", [], "SQL."),
        "x " * 400,
        passage("ML Engineer", ["Python"], "Feature pipelines on Spark. " * 10),
    ]
    together = reranker.score(query, texts, 256)
    for i, text in enumerate(texts):
        assert reranker.score(query, [text], 256)[0] == pytest.approx(together[i], abs=0.01)


def test_token_limit_applies_per_call_and_long_passages_are_truncated(reranker) -> None:  # type: ignore[no-untyped-def]
    long_text = passage("Platform Engineer", ["Go"], "Kubernetes operators. " * 2000)
    short = reranker.score("platform engineer", [long_text], 32)
    full = reranker.score("platform engineer", [long_text], 512)
    assert len(short) == len(full) == 1
    assert short != full  # different truncation, different input
    assert reranker.score("anything", [], 128) == []
