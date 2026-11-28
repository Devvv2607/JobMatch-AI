"""Project status in one screen (the /status command). Read-only, standard library only.

PowerShell:  python .claude\\scripts\\status.py
Git Bash:    python .claude/scripts/status.py

Shows: branch and how it stands against origin/main, running containers, judge label
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
    for part in (git_state, containers, labels, resources, ci, ingest):
        try:
            part()
        except Exception as exc:  # one broken part must not hide the rest
            print(f"  ({part.__name__} failed: {type(exc).__name__}: {exc})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
