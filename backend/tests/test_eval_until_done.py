"""The quota-aware judge loop's decisions (app/eval/until_done.py)."""

from datetime import UTC, datetime, timedelta
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


class FakeClock:
    """Wall clock that sleep() advances; jump() is a laptop sleep (time passes, no poll)."""

    def __init__(self, start: datetime) -> None:
        self.t = start
        self.sleeps: list[float] = []

    def now(self) -> datetime:
        return self.t

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.t += timedelta(seconds=seconds)
        if len(self.sleeps) == 3:  # the VM pauses for 10 hours mid-wait
            self.t += timedelta(hours=10)


def test_wait_polls_the_wall_clock_so_a_laptop_sleep_cannot_delay_the_resume(
    tmp_path: Path,
) -> None:
    from app.eval.until_done import POLL, wait_until

    clock = FakeClock(NOW)
    resume_at = NOW + timedelta(hours=12)
    log_path = tmp_path / "run.log"
    wait_until(resume_at, log_path, now=clock.now, sleep=clock.sleep)
    assert clock.t >= resume_at
    assert clock.t - resume_at <= timedelta(seconds=POLL)  # resumed within one poll
    assert max(clock.sleeps) <= POLL  # never one long sleep
    # After the 10 h jump only ~2 h of polling remain, not another 12 h.
    assert len(clock.sleeps) < 2 * 3600 / POLL + 10


def test_wait_logs_an_hourly_heartbeat(tmp_path: Path) -> None:
    from app.eval.until_done import wait_until

    class Steady(FakeClock):
        def sleep(self, seconds: float) -> None:
            self.sleeps.append(seconds)
            self.t += timedelta(seconds=seconds)

    clock = Steady(NOW)
    log_path = tmp_path / "run.log"
    wait_until(NOW + timedelta(hours=3, minutes=10), log_path, now=clock.now, sleep=clock.sleep)
    beats = [line for line in log_path.read_text().splitlines() if "heartbeat" in line]
    assert len(beats) == 3
    assert "resume at 2026-11-27T15:10:00+00:00" in beats[0]


def test_wait_returns_at_once_when_the_time_has_passed(tmp_path: Path) -> None:
    from app.eval.until_done import wait_until

    clock = FakeClock(NOW)
    wait_until(NOW - timedelta(minutes=1), tmp_path / "run.log", now=clock.now, sleep=clock.sleep)
    assert clock.sleeps == []
