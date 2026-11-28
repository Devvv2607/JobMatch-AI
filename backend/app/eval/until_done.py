"""Run a judge until every pair is done, waiting out quotas on its own (owner decision
2026-11-27, after Claude Code's memory reaper killed the background judge shells).

Meant for a detached, named container:

    python -m app.eval.until_done --log /eval/private/logs/gemini-v3.log -- \
        --set eval-2026-11-25 --input-version 3 --ids ... --out judge-v3.jsonl

Each round starts a fresh `python -m app.eval.cli judge <args>` process (so no client
or connection outlives a long wait), appends its output to the log, and decides from the
judge's own summary line:
- "0 pairs left": done, exit 0;
- Gemini's daily budget or quota: sleep until the next midnight Pacific plus a minute;
- Groq's daily quota: retry in an hour;
- stopped after consecutive failures, or any other ending: retry in 10 minutes; after
  MAX_CRASHES such rounds in a row, stop working.
Waits are short polls against the wall clock (wait_until), never one long sleep: on
2026-11-27 a 744 min sleep never ended on time, because laptop sleep pauses the Docker
VM and time.sleep counts the VM's monotonic clock, which stops while paused. After a
wake the wall clock is right again, so the next poll (at most POLL seconds of awake time
later) sees the resume time has passed. An hourly heartbeat line shows the wait is alive.
When done (or giving up) it logs why and idles rather than exiting, because the
containers run with restart policy unless-stopped (so they survive a Docker Desktop
restart) and an exit would just restart them. Before each round it checks that the
output file ends with a complete JSON line; if not (a kill mid-write), it idles without
touching the file, so a backup comes before any repair. The judge is resumable: it skips
pairs already judged from the same input (sha256), and appends one fsynced line per
pair, so a resumed run never writes a duplicate.
"""

import argparse
import json
import subprocess
import sys
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.eval.quota import next_reset

GROQ_RETRY = 3600
FAILURE_RETRY = 600
MAX_CRASHES = 5
POLL = 300  # seconds between wall-clock checks while waiting
HEARTBEAT = 3600  # a "still waiting" log line this often


def utc_now() -> datetime:
    return datetime.now(UTC)


def decide(output: str, now: datetime) -> tuple[str, float]:
    """(what happened, seconds to wait); ("done", 0) ends the loop."""
    if "\n0 pairs left" in "\n" + output:
        return "done", 0.0
    if "STOPPED: gemini daily" in output:
        return "gemini daily cap", (next_reset(now) - now).total_seconds() + 60
    if "STOPPED: groq daily quota" in output:
        return "groq daily quota", GROQ_RETRY
    if "STOPPED after consecutive failures" in output:
        return "consecutive failures", FAILURE_RETRY
    return "unexpected end", FAILURE_RETRY


def log(path: Path, text: str) -> None:
    stamp = datetime.now(UTC).isoformat(timespec="seconds")
    with path.open("a", encoding="utf-8") as f:
        f.write(f"[{stamp}] {text}\n")
    print(f"[{stamp}] {text}", flush=True)


def out_file(judge_args: list[str]) -> Path | None:
    """The judge's output file, from its --set and --out arguments."""
    from app.eval import EVAL_DIR

    def value(flag: str, default: str | None) -> str | None:
        return judge_args[judge_args.index(flag) + 1] if flag in judge_args else default

    name, out = value("--set", None), value("--out", "judge.jsonl")
    return EVAL_DIR / "labels" / name / out if name and out else None


def last_line_ok(path: Path) -> bool:
    """True if the file is absent, empty, or ends with a complete JSON line."""
    if not path.exists() or path.stat().st_size == 0:
        return True
    data = path.read_bytes()
    if not data.endswith(b"\n"):
        return False
    last = data.rstrip(b"\n").rsplit(b"\n", 1)[-1]
    try:
        json.loads(last)
    except ValueError:
        return False
    return True


def wait_until(
    resume_at: datetime,
    log_path: Path,
    *,
    now: Callable[[], datetime] = utc_now,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    """Return once the wall clock reaches resume_at, checking every POLL seconds."""
    last_beat = now()
    while (t := now()) < resume_at:
        if (t - last_beat).total_seconds() >= HEARTBEAT:
            left = (resume_at - t).total_seconds() / 60
            log(
                log_path,
                f"heartbeat: waiting, resume at {resume_at.isoformat(timespec='seconds')}"
                f" ({left:.0f} min left)",
            )
            last_beat = t
        sleep(min(POLL, max(1.0, (resume_at - t).total_seconds())))


def idle(log_path: Path, why: str) -> None:
    """Stay up without working: with restart policy unless-stopped, an exit would only
    restart the container and repeat the round. Stop it with `docker stop`."""
    log(log_path, f"{why}; idling (stop with docker stop)")
    while True:
        time.sleep(3600)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.eval.until_done")
    parser.add_argument("--log", required=True)
    parser.add_argument("--max-hours", type=float, default=72.0)
    parser.add_argument("judge_args", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    judge_args = [a for a in args.judge_args if a != "--"]
    log_path = Path(args.log)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    out = out_file(judge_args)
    deadline = utc_now() + timedelta(hours=args.max_hours)  # wall clock, as for waits
    crashes = 0
    command = [sys.executable, "-m", "app.eval.cli", "judge", *judge_args]
    log(log_path, f"start: {' '.join(command)}")
    while utc_now() < deadline:
        if out is not None and not last_line_ok(out):
            # Only a kill in the middle of a write leaves this. Never truncate here:
            # the owner backs up first, then the partial line is removed by hand.
            idle(log_path, f"{out.name} ends with an incomplete line; nothing judged")
        # Output streams into the log as it happens (so progress is visible), then this
        # round's part is read back to decide what to do next.
        start = log_path.stat().st_size
        with log_path.open("ab") as f:
            result = subprocess.run(  # noqa: S603 - our own interpreter and module
                command, stdout=f, stderr=subprocess.STDOUT, check=False
            )
        with log_path.open("rb") as f:
            f.seek(start)
            output = f.read().decode("utf-8", errors="replace")
        ended = utc_now()
        what, wait = decide(output, ended)
        if what == "done":
            idle(log_path, "done: 0 pairs left")
        crashes = crashes + 1 if what in ("unexpected end", "consecutive failures") else 0
        if crashes >= MAX_CRASHES:
            idle(
                log_path,
                f"giving up after {crashes} failed rounds in a row (exit {result.returncode})",
            )
        resume_at = ended + timedelta(seconds=wait)
        log(
            log_path,
            f"{what} (exit {result.returncode}); waiting {wait / 60:.0f} min, until "
            f"{resume_at.isoformat(timespec='seconds')} (polling every {POLL // 60} min)",
        )
        wait_until(resume_at, log_path)
    idle(log_path, f"giving up: {args.max_hours} h passed")
    return 1


if __name__ == "__main__":
    sys.exit(main())
