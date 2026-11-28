"""List files that must never be in the repo (the guard hook's rules, applied to what is
already tracked and to what this branch changes). Exit 1 if any are found.

    python .claude/scripts/forbidden_files.py            # tracked files + branch diff
    python .claude/scripts/forbidden_files.py --base origin/main

Used by /pre-pr and by CI (the Backend job), so a file staged outside Claude Code (or
with the hook off) is still caught before merge.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / ".claude" / "hooks"))
from guard import forbidden_path  # noqa: E402


def git_lines(*args: str) -> list[str]:
    r = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=False)
    return [line for line in r.stdout.splitlines() if line.strip()]


def find(base: str | None) -> list[tuple[str, str]]:
    paths = set(git_lines("ls-files"))
    if base:
        paths |= set(git_lines("diff", "--name-only", "--diff-filter=AM", f"{base}...HEAD"))
    return sorted((p, why) for p in paths if (why := forbidden_path(p)))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default=None, help="also check files changed since this ref")
    args = parser.parse_args(argv)
    hits = find(args.base)
    for path, why in hits:
        print(f"FORBIDDEN {path}: {why}")
    print(f"{len(hits)} forbidden file(s)" if hits else "no forbidden files")
    return 1 if hits else 0


if __name__ == "__main__":
    sys.exit(main())
