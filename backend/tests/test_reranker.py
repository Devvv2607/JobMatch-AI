"""The real int8 cross-encoder. Baked into the Docker image, so these run there (and in
CI's image job); on a host without the model they are skipped, never faked."""

from pathlib import Path

import pytest

from app.core.config import get_settings
from app.retrieval.service import passage

settings = get_settings()
MODEL_DIR = Path(settings.reranker_model_dir)
pytestmark = pytest.mark.skipif(
    not (MODEL_DIR / settings.reranker_model_file).exists(),
    reason=f"reranker model not present at {MODEL_DIR}",
)


@pytest.fixture(scope="module")
def reranker():  # type: ignore[no-untyped-def]
    from app.ml.reranker import OnnxReranker

    return OnnxReranker(MODEL_DIR, settings.reranker_model_file, max_tokens=256)


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
    chef, engineer, sales = reranker.score(query, passages)
    assert engineer > chef and engineer > sales
    assert engineer > 0 > chef


def test_scores_do_not_depend_on_batch_composition(reranker) -> None:  # type: ignore[no-untyped-def]
    text = passage("Data Engineer", ["Spark"], "Batch pipelines in Spark and Airflow.")
    alone = reranker.score("data engineer spark", [text])[0]
    padded = reranker.score("data engineer spark", [text, "x " * 400])[0]
    assert alone == pytest.approx(padded, abs=1e-3)


def test_long_passages_are_truncated_not_rejected(reranker) -> None:  # type: ignore[no-untyped-def]
    long_text = passage("Platform Engineer", ["Go"], "Kubernetes operators. " * 2000)
    assert len(reranker.score("platform engineer", [long_text])) == 1
    assert reranker.score("anything", []) == []
