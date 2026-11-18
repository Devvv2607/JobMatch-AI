import subprocess
import sys

from app.core.config import Settings
from app.worker import cron_jobs, ingest_jobs, purge_refresh_tokens


def test_ingest_cron_is_off_by_default() -> None:
    names = [job.name for job in cron_jobs(Settings())]
    assert names == ["cron:purge_refresh_tokens"]


def test_ingest_cron_is_scheduled_when_enabled() -> None:
    jobs = cron_jobs(Settings(ingest_cron_enabled=True, ingest_cron_hours="2, 14"))
    ingest = next(job for job in jobs if job.name == "cron:ingest_jobs")
    assert ingest.coroutine is ingest_jobs
    assert ingest.hour == {2, 14}
    assert ingest.minute == 10
    assert ingest.unique is True
    assert any(job.coroutine is purge_refresh_tokens for job in jobs)


def test_the_worker_does_not_import_ml_models_at_startup() -> None:
    """Importing the worker (what arq does at boot) loads no model code at all. The
    embedder is imported lazily on the first ingest; the cross-encoder never."""
    code = (
        "import sys, app.worker; "
        "loaded = [m for m in sys.modules "
        "if m.startswith(('onnxruntime', 'app.ml', 'app.retrieval'))"
        " or 'rerank' in m or 'cross_encoder' in m]; "
        "print(loaded); sys.exit(1 if loaded else 0)"
    )
    result = subprocess.run(  # noqa: S603  # fixed arguments
        [sys.executable, "-c", code], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stdout + result.stderr
