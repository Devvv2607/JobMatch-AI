import subprocess
import sys

from app.core.config import Settings, get_settings
from app.worker import WorkerSettings, cron_jobs, ingest_jobs, purge_refresh_tokens


def defaults(**overrides: object) -> Settings:
    """Settings from the code's defaults, whatever the developer's .env says."""
    values = {
        name: field.default
        for name, field in Settings.model_fields.items()
        if name.startswith("ingest_cron")
    }
    return Settings(**{**values, **overrides})


def test_daily_ingest_is_on_by_default_at_three_am_india_time() -> None:
    settings = defaults()
    ingest = next(job for job in cron_jobs(settings) if job.name == "cron:ingest_jobs")
    assert ingest.coroutine is ingest_jobs
    assert (ingest.hour, ingest.minute) == ({3}, 0)
    assert ingest.unique is True
    assert settings.ingest_cron_timezone == "Asia/Kolkata"
    assert str(WorkerSettings.timezone) == get_settings().ingest_cron_timezone
    assert ingest_jobs in WorkerSettings.functions  # enqueue-able by name (catch-up)


def test_ingest_cron_can_be_turned_off_or_moved() -> None:
    names = [job.name for job in cron_jobs(defaults(ingest_cron_enabled=False))]
    assert names == ["cron:purge_refresh_tokens"]
    jobs = cron_jobs(defaults(ingest_cron_hours="2, 14", ingest_cron_minute=30))
    ingest = next(job for job in jobs if job.name == "cron:ingest_jobs")
    assert (ingest.hour, ingest.minute) == ({2, 14}, 30)
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
