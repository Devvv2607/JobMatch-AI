"""Project status in one screen (the /status command). Changes nothing in the repo or the
stack; it does run `git fetch origin main` (network) to compare with main. Stdlib only.

PowerShell:  python .claude\\scripts\\status.py
Git Bash:    python .claude/scripts/status.py

Shows: a guard self-check first (the hook launcher must refuse one harmless probe and
allow a normal command; exit code 1 if it does not), then the branch and how it stands against origin/main, running containers, judge label
counts, free RAM and disk (with the CLAUDE.md thresholds), the latest CI run for this
branch, and the last ingest run. Any part that cannot be read says so and the rest still
prints.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / ".claude" / "hooks"))
from guard import DISK_WARN_GB, RAM_WARN_GB, free_disk_gb, free_ram_gb  # noqa: E402


def sh(*cmd: str, timeout: int = 30) -> tuple[int, str]:
    try:
        r = subprocess.run(
            list(cmd), cwd=ROOT, capture_output=True, text=True, timeout=timeout, check=False,
            encoding="utf-8", errors="replace",
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return 1, f"{type(exc).__name__}: {exc}"
    return r.returncode, (r.stdout or r.stderr).strip()


def section(title: str) -> None:
    print(f"\n== {title}")


LAUNCHER = ROOT / ".claude" / "hooks" / "run_guard.sh"
PROBE_BLOCK = "cat .env.guard-selfcheck"  # harmless: the file does not exist
PROBE_ALLOW = "git status --short"


def find_sh() -> str | None:
    """The POSIX shell Claude Code runs hooks with (Git Bash's on Windows)."""
    import shutil

    for candidate in (
        shutil.which("sh"),
        r"C:\Program Files\Git\bin\sh.exe",
        r"C:\Program Files\Git\usr\bin\sh.exe",
    ):
        if candidate and Path(candidate).exists():
            return candidate
    return None


def guard_interpreter() -> str:
    """Which interpreter run_guard.sh picks (the same order as the launcher)."""
    import shutil

    for py in (ROOT / "backend/.venv/Scripts/python.exe", ROOT / "backend/.venv/bin/python"):
        if py.exists():
            return str(py.relative_to(ROOT))
    return "py -3" if shutil.which("py") else "none (every command would be blocked)"


def run_guard(shell: str, command: str) -> tuple[int, str]:
    import os

    payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": command}, "cwd": str(ROOT)})
    try:
        r = subprocess.run(
            [shell, str(LAUNCHER)], input=payload, capture_output=True, text=True, timeout=60,
            env={**os.environ, "CLAUDE_PROJECT_DIR": str(ROOT)}, check=False,
            encoding="utf-8", errors="replace",
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return -1, f"{type(exc).__name__}: {exc}"
    return r.returncode, r.stderr.strip()


def guard_selfcheck() -> bool:
    """The hook as Claude Code runs it: a harmless probe must be refused, a normal command
    allowed. Returns False if the guard is not working."""
    section("Guard self-check")
    shell = find_sh()
    if shell is None:
        print("FAIL: no sh found, so Claude Code cannot run the hook either (install Git for Windows)")
        return False
    print(f"interpreter: {guard_interpreter()}")
    code_b, err_b = run_guard(shell, PROBE_BLOCK)
    code_a, err_a = run_guard(shell, PROBE_ALLOW)
    ok_b = code_b == 2 and "Blocked by .claude/hooks/guard.py" in err_b
    ok_a = code_a == 0
    print(f"probe `{PROBE_BLOCK}`: {'refused (ok)' if ok_b else f'NOT REFUSED (exit {code_b}): {err_b[:200]}'}")
    print(f"probe `{PROBE_ALLOW}`: {'allowed (ok)' if ok_a else f'NOT ALLOWED (exit {code_a}): {err_a[:200]}'}")
    if not (ok_b and ok_a):
        print("GUARD NOT WORKING: stop and fix it before running anything else.")
    return ok_b and ok_a


def git_state() -> None:
    section("Git")
    _, branch = sh("git", "rev-parse", "--abbrev-ref", "HEAD")
    _, dirty = sh("git", "status", "--porcelain")
    sh("git", "fetch", "-q", "origin", "main")
    _, counts = sh("git", "rev-list", "--left-right", "--count", "origin/main...HEAD")
    behind, ahead = (counts.split() + ["?", "?"])[:2]
    print(f"branch {branch}: {ahead} ahead / {behind} behind origin/main; "
          f"{len(dirty.splitlines()) if dirty else 0} uncommitted changes")


def containers() -> None:
    section("Containers (running)")
    code, out = sh("docker", "ps", "--format", "{{.Names}}\t{{.Status}}")
    print(out if code == 0 and out else ("none" if code == 0 else f"docker not reachable: {out[:200]}"))


def labels() -> None:
    section("Judge labels (records per file)")
    found = False
    for f in sorted((ROOT / "eval" / "labels").glob("*/judge*.jsonl")):
        if "sample" in f.name:
            continue
        with f.open("rb") as fh:
            n = sum(1 for line in fh if line.strip())
        print(f"{f.parent.name}/{f.name}: {n}")
        found = True
    if not found:
        print("no label files")


def resources() -> None:
    section("Resources")
    ram, disk = free_ram_gb(), free_disk_gb(ROOT)
    ram_s = "?" if ram is None else f"{ram:.1f} GB" + ("  LOW" if ram < RAM_WARN_GB else "")
    disk_s = "?" if disk is None else f"{disk:.1f} GB" + ("  STOP: under 15 GB" if disk < DISK_WARN_GB else "")
    print(f"free RAM {ram_s} (warn under {RAM_WARN_GB:.0f} GB); free disk C: {disk_s}")


def ci() -> None:
    section("Latest CI run (this branch, else main)")
    _, branch = sh("git", "rev-parse", "--abbrev-ref", "HEAD")
    for b in dict.fromkeys((branch, "main")):
        code, out = sh(
            "gh", "run", "list", "--branch", b, "--limit", "1",
            "--json", "status,conclusion,displayTitle,createdAt,headSha,url",
        )
        if code != 0:
            print(f"gh not available: {out[:200]}")
            return
        runs = json.loads(out or "[]")
        if runs:
            r = runs[0]
            print(f"{b}: {r['conclusion'] or r['status']} | {r['displayTitle'][:70]} | "
                  f"{r['headSha'][:7]} | {r['createdAt']}\n  {r['url']}")
            return
    print("no runs found")


def ingest() -> None:
    section("Last ingest run")
    q = (
        "select max(started_at), max(finished_at), "
        "string_agg(source || ':' || status, ' ' order by source) "
        "from ingest_runs where run_id = (select run_id from ingest_runs order by started_at desc limit 1)"
    )
    code, out = sh("docker", "exec", "jobmatch-db-1", "psql", "-U", "jobmatch", "-d", "jobmatch", "-Atc", q)
    if code != 0:
        print(f"database not reachable: {out[:200]}")
        return
    started, finished, statuses = (out.split("|") + ["", "", ""])[:3]
    print(f"started {started}, finished {finished or 'not finished'}\n  {statuses}")


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print(f"JobMatch status ({ROOT})")
    try:
        guard_ok = guard_selfcheck()
    except Exception as exc:  # report, never hide, a broken self-check
        print(f"  (guard self-check failed: {type(exc).__name__}: {exc})")
        guard_ok = False
    for part in (git_state, containers, labels, resources, ci, ingest):
        try:
            part()
        except Exception as exc:  # one broken part must not hide the rest
            print(f"  ({part.__name__} failed: {type(exc).__name__}: {exc})")
    return 0 if guard_ok else 1


if __name__ == "__main__":
    sys.exit(main())
