"""The quota-aware judge loop's decisions (app/eval/until_done.py)."""

from datetime import UTC, datetime
from pathlib import Path

from app.eval.until_done import FAILURE_RETRY, GROQ_RETRY, decide

NOW = datetime(2026, 11, 27, 12, 0, tzinfo=UTC)  # 04:00 Pacific


def test_done_only_on_the_judges_zero_left_line() -> None:
    assert decide("JudgeRun(...)\n0 pairs left\n", NOW) == ("done", 0.0)
    assert decide("30 pairs left\n", NOW)[0] == "unexpected end"
    assert decide("STOPPED: groq daily quota reached; 30 pairs left. Resume", NOW)[0] != "done"


def test_gemini_waits_until_midnight_pacific_plus_a_minute() -> None:
    what, wait = decide("STOPPED: gemini daily request budget reached; 398 pairs left", NOW)
    assert what == "gemini daily cap"
    assert wait == 20 * 3600 + 60  # 04:00 -> 00:00 Pacific, + 60 s


def test_groq_quota_and_failures_retry_later() -> None:
    assert decide("STOPPED: groq daily quota reached; 30 pairs left", NOW) == (
        "groq daily quota",
        GROQ_RETRY,
    )
    assert decide("STOPPED after consecutive failures (x); 5 pairs left", NOW) == (
        "consecutive failures",
        FAILURE_RETRY,
    )


def test_out_file_and_last_line_check(tmp_path: Path) -> None:
    from app.eval import EVAL_DIR
    from app.eval.until_done import last_line_ok, out_file

    args = ["--set", "s1", "--provider", "groq", "--out", "judge-x.jsonl"]
    assert out_file(args) == EVAL_DIR / "labels" / "s1" / "judge-x.jsonl"
    assert out_file(["--set", "s1"]) == EVAL_DIR / "labels" / "s1" / "judge.jsonl"
    path = tmp_path / "judge.jsonl"
    assert last_line_ok(path)  # absent
    path.write_text('{"pair_id": "a"}\n{"pair_id": "b"}\n')
    assert last_line_ok(path)
    path.write_text('{"pair_id": "a"}\n{"pair_id": "b", "lab')
    assert not last_line_ok(path)
    path.write_text('{"pair_id": "a"}\n{"pair_id": "b", "lab\n')
    assert not last_line_ok(path)
