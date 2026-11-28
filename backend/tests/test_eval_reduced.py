"""Reduced corpus selection, hashing and the regression gate rule (app/eval/reduced.py).
The export/load round trip runs end to end in CI's docker job (`cli gate`)."""

import gzip
import json
from pathlib import Path

import pytest

from app.eval.reduced import (
    _write_gz,
    choose_jobs,
    gate_check,
    sha256,
    sync_url,
    verify,
)


def test_choose_jobs_keeps_every_pooled_job_and_samples_by_source() -> None:
    searchable = {f"g{i}": "greenhouse" for i in range(80)}
    searchable |= {f"h{i}": "himalayas" for i in range(20)}
    keep, extra = choose_jobs(["g1", "h1", "gone"], searchable, 10, seed=1)
    assert keep == ["g1", "h1"]  # "gone" is not searchable any more
    assert len(extra) == 10
    assert sum(j.startswith("g") for j in extra) == 8  # 79 vs 19 of the rest
    assert not set(extra) & set(keep)
    assert choose_jobs(["g1", "h1"], searchable, 10, seed=1)[1] == extra  # seeded


def test_gzip_bytes_are_reproducible(tmp_path: Path) -> None:
    _write_gz(tmp_path / "a.csv.gz", b"id\n1\n")
    _write_gz(tmp_path / "b.csv.gz", b"id\n1\n")
    assert sha256(tmp_path / "a.csv.gz") == sha256(tmp_path / "b.csv.gz")
    assert gzip.decompress((tmp_path / "a.csv.gz").read_bytes()) == b"id\n1\n"


def test_verify_rejects_a_changed_file(tmp_path: Path) -> None:
    for name in ("companies.csv.gz", "jobs.csv.gz"):
        _write_gz(tmp_path / name, b"id\n")
    files = {n: {"sha256": sha256(tmp_path / n)} for n in ("companies.csv.gz", "jobs.csv.gz")}
    (tmp_path / "manifest.json").write_text(json.dumps({"files": files}))
    assert verify(tmp_path)["files"] == files
    _write_gz(tmp_path / "jobs.csv.gz", b"id\n2\n")
    with pytest.raises(ValueError, match="sha256"):
        verify(tmp_path)


def test_gate_fails_only_on_a_drop_beyond_the_margin() -> None:
    baseline = {"ndcg10": {"query:fused": 0.66, "query:rerank_10_128": 0.65}}
    assert gate_check({"query:fused": 0.645, "query:rerank_10_128": 0.70}, baseline) == []
    failures = gate_check({"query:fused": 0.63}, baseline)
    assert len(failures) == 2
    assert "query:fused: NDCG@10 0.6300 < baseline 0.6600" in failures[0]
    assert failures[1] == "query:rerank_10_128: not measured"


def test_sync_url_drops_the_driver_and_can_switch_database() -> None:
    url = "postgresql+psycopg://u:p@db:5432/jobmatch"
    assert sync_url(url) == "postgresql://u:p@db:5432/jobmatch"
    assert sync_url(url, "other").endswith("/other")
