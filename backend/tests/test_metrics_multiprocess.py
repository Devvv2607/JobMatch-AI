"""/metrics with several uvicorn workers (PROMETHEUS_MULTIPROC_DIR set)."""

from pathlib import Path

import httpx
import pytest


async def test_metrics_sum_worker_files_when_multiprocess_dir_is_set(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from prometheus_client import Counter, values

    monkeypatch.setenv("PROMETHEUS_MULTIPROC_DIR", str(tmp_path))
    # What a worker process does at import time when the variable is set.
    monkeypatch.setattr(values, "ValueClass", values.MultiProcessValue())  # type: ignore[no-untyped-call]
    counter = Counter("test_worker_events_total", "events", registry=None)
    counter.inc(3)

    response = await client.get("/metrics")
    assert response.status_code == 200
    assert "test_worker_events_total 3.0" in response.text
