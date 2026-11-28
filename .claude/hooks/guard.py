"""PreToolUse guard for Bash and PowerShell commands (see CLAUDE.md, "Guard rails").

Claude Code sends the tool call as JSON on stdin. Exit 2 with a message on stderr blocks
the call and the message goes back to Claude; exit 0 lets it run (with a warning printed
as JSON on stdout when resources are low). Standard library only; Windows and Linux.

Blocks:
- docker compose down, docker system/volume/image/container/builder prune, docker
  volume rm, any docker command with --remove-orphans;
- git push to main, and every force push (--force, -f, --force-with-lease, +refspec);
- rm -rf / Remove-Item -Recurse -Force on a path outside the working tree (the
  session scratch space under %TEMP%/claude is allowed), or on the repo root itself;
- reading .env files (cat, Get-Content, grep, ...), except .env.example;
- git add / git commit that would stage or commit .env*, eval/private/**, backups/**,
  or a .pdf/.docx outside backend/tests/fixtures/resumes/ (synthetic resumes only).
Warns (never blocks) when free RAM < 2 GB or free disk < 15 GB before a Docker build,
a model load (ingest, embedding, eval, benchmarks, tests in the image) or Playwright.
Errors inside the guard fail closed (exit 2, with the reason).
"""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path, PurePosixPath

RAM_WARN_GB = 2.0
DISK_WARN_GB = 15.0
RESUME_DIR = "backend/tests/fixtures/resumes/"

SEPARATORS = re.compile(r"\s*(?:&&|\|\||;|\||\n)\s*")
HEREDOC = re.compile(r"<<-?\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1")
ENV_READERS = {
    "cat", "head", "tail", "less", "more", "type", "get-content", "gc", "grep", "rg",
    "sed", "awk", "source", ".", "strings", "xxd", "od", "base64", "select-string",
    "sls", "bat", "nl", "cut", "sort", "uniq", "diff", "findstr", "egrep", "fgrep",
}
DOCKER = {"docker", "docker.exe", "docker-compose", "docker-compose.exe"}
COMPOSE_OPTS_WITH_VALUE = {
    "-f", "--file", "-p", "--project-name", "--env-file", "--profile",
    "--project-directory", "--ansi", "--parallel", "--progress",
}
HEAVY = re.compile(
    r"docker\s+(compose\s+)?build|docker\s+compose\s+up\b.*--build|\bmake\s+(up|ingest|"
    r"ingest-embed|bench-search|test|test-all|eval|eval-final|bm25|discover)\b|"
    r"app\.ingest\.cli\s+(run|embed)|app\.eval\.cli\s+(gate|pool|report|final)|"
    r"scripts\.bench_search|playwright|shoot\.mjs|\bnext\s+build\b|npm\s+(--prefix\s+\S+\s+)?run\s+build",
    re.I,
)

SAFE_DOWN = (
    "`docker compose down` stops and removes every service (db, redis, worker) and the "
    "restart settings set on them. Safe: `docker compose stop <service>` for one service, "
    "or ask the owner first."
)
SAFE_PRUNE = (
    "prune deletes images, containers, volumes or build cache for every project on this "
    "Docker host. Safe: remove one named image or container you have checked, or ask the "
    "owner (disk cleanup is their call)."
)
SAFE_VOLUME = (
    "`docker volume rm` deletes a data volume (the database lives in one). Safe: "
    "`make backup` and ask the owner; never remove a volume yourself."
)
SAFE_ORPHANS = (
    "--remove-orphans deletes containers compose does not define, including the detached "
    "judge containers (jm-judge-*) and other projects' containers. Safe: leave orphans "
    "alone, or `docker stop <name>` / `docker rm <name>` one you have checked."
)
SAFE_FORCE = (
    "a force push rewrites published history. Safe: add a new commit (or `git revert`) "
    "and push normally."
)
SAFE_MAIN = (
    "main is protected: changes reach it only through a pull request (squash merge). "
    "Safe: push your branch (`git push -u origin <branch>`) and open a PR with "
    "`gh pr create`."
)


# ---------------------------------------------------------------- parsing helpers


def strip_heredocs(command: str) -> str:
    """Drop heredoc bodies: their text is data (a file, a commit message), not commands."""
    lines = command.split("\n")
    out: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        out.append(line)
        m = HEREDOC.search(line)
        i += 1
        if m:
            end = m.group(2)
            while i < len(lines) and lines[i].strip() != end:
                i += 1
            i += 1  # the terminator
    return "\n".join(out)


def split_commands(command: str) -> list[str]:
    return [c for c in SEPARATORS.split(strip_heredocs(command)) if c.strip()]


def words(segment: str, powershell: bool = False) -> list[str]:
    try:
        if powershell:  # backslashes are path separators there, not escapes
            return [w.strip("'\"") for w in shlex.split(segment, posix=False)]
        return shlex.split(segment, posix=True)
    except ValueError:
        return segment.split()


def strip_prefix(w: list[str]) -> list[str]:
    """Drop VAR=value assignments and wrappers (sudo, time, ...) before the command."""
    i = 0
    while i < len(w) and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", w[i]):
        i += 1
    while i < len(w) and w[i] in ("sudo", "command", "exec", "time", "nohup", "&"):
        i += 1
    return w[i:]


def base(word: str) -> str:
    return PurePosixPath(word.replace("\\", "/")).name.lower()


def to_path(text: str) -> Path:
    """A shell path as this OS sees it: Git Bash's /c/Users/... is C:/Users/... on Windows."""
    if sys.platform == "win32":
        m = re.match(r"^/([a-zA-Z])(/.*)?$", text)
        if m:
            return Path(f"{m.group(1).upper()}:{m.group(2) or '/'}")
    return Path(text)


def resolve(text: str, cwd: Path) -> Path:
    p = to_path(text)
    return (p if p.is_absolute() else cwd / p).resolve()


def inside(path: Path, roots: list[Path]) -> bool:
    for root in roots:
        try:
            path.relative_to(root)
            return True
        except ValueError:
            continue
    return False


def allowed_roots(project: Path) -> list[Path]:
    # The repo, plus Claude Code's own disposable scratch space (session scratchpads).
    return [project.resolve(), (Path(tempfile.gettempdir()) / "claude").resolve()]


def run_git(cwd: Path, *args: str) -> list[str]:
    try:
        r = subprocess.run(
            ["git", *args], cwd=cwd, capture_output=True, text=True, timeout=20, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return []
    return [line for line in r.stdout.splitlines() if line.strip()]


# ---------------------------------------------------------------- checks


def forbidden_path(path: str) -> str | None:
    """Why this repo-relative path must never be committed, or None."""
    p = path.replace("\\", "/")
    while p.startswith("./"):
        p = p[2:]
    name = PurePosixPath(p).name.lower()
    if name.startswith(".env") and name != ".env.example":
        return "secrets: .env files hold API keys"
    if p.startswith("eval/private/") or "/eval/private/" in p or p == "eval/private":
        return "eval/private/: personal data, previews and logs"
    if p.startswith("backups/") or p == "backups":
        return "backups/: database dumps"
    if name.endswith((".pdf", ".docx")) and not p.startswith(RESUME_DIR):
        return f"a .pdf/.docx outside {RESUME_DIR} (resumes are personal data)"
    return None


def check_docker(w: list[str]) -> str | None:
    if not w or base(w[0]) not in DOCKER:
        return None
    low = [a.lower() for a in w]
    if "--remove-orphans" in low:
        return SAFE_ORPHANS
    rest = low[1:]
    if base(w[0]).startswith("docker-compose"):
        rest = ["compose", *rest]
    if rest[:1] == ["compose"]:
        i = 1
        while i < len(rest) and rest[i].startswith("-"):
            i += 2 if rest[i] in COMPOSE_OPTS_WITH_VALUE else 1
        if i < len(rest) and rest[i] == "down":
            return SAFE_DOWN
        return None
    if len(rest) >= 2 and rest[1] == "prune" and rest[0] in (
        "system", "volume", "image", "container", "builder", "network", "buildx",
    ):
        return SAFE_PRUNE
    if len(rest) >= 2 and rest[0] == "volume" and rest[1] in ("rm", "remove"):
        return SAFE_VOLUME
    return None


def git_args(w: list[str]) -> list[str] | None:
    """Arguments after `git` (skipping -C <dir>, -c k=v and other globals), or None."""
    if not w or base(w[0]) not in ("git", "git.exe"):
        return None
    i = 1
    while i < len(w) and w[i].startswith("-"):
        i += 2 if w[i] in ("-C", "-c") else 1
    return w[i:]


def check_git_push(args: list[str], cwd: Path) -> str | None:
    if not args or args[0] != "push":
        return None
    rest = args[1:]
    for a in rest:
        if a in ("--force", "--force-with-lease", "--force-if-includes", "--mirror") or (
            a.startswith("--force-with-lease=")
        ):
            return SAFE_FORCE
        if a.startswith("-") and not a.startswith("--") and "f" in a[1:]:
            return SAFE_FORCE
    positional = [a for a in rest if not a.startswith("-")]
    refspecs = positional[1:]  # the first is the remote
    if any(r.startswith("+") for r in refspecs):
        return SAFE_FORCE
    if "--all" in rest:
        return SAFE_MAIN
    if refspecs:
        dests = [r.split(":")[-1] for r in refspecs]
    else:
        dests = run_git(cwd, "rev-parse", "--abbrev-ref", "HEAD")[:1]
    if any(d in ("main", "refs/heads/main") for d in dests):
        return SAFE_MAIN
    if any(r == "HEAD" for r in refspecs) and run_git(cwd, "rev-parse", "--abbrev-ref", "HEAD")[
        :1
    ] == ["main"]:
        return SAFE_MAIN
    return None


def check_git_stage(args: list[str], cwd: Path) -> str | None:
    if not args or args[0] not in ("add", "stage", "commit"):
        return None
    paths: list[str] = []
    if args[0] in ("add", "stage"):
        opts = [a for a in args[1:] if a not in ("-n", "--dry-run")]
        paths = [
            line.split("'", 2)[1]
            for line in run_git(cwd, "add", "--dry-run", *opts)
            if line.startswith("add '")
        ]
        paths += [a for a in opts if not a.startswith("-")]  # named files, even ignored ones
    else:
        paths = run_git(cwd, "diff", "--cached", "--name-only")
        rest = args[1:]
        short = [a for a in rest if a.startswith("-") and not a.startswith("--")]
        if "--all" in rest or any("a" in s[1:] for s in short):
            paths += run_git(cwd, "diff", "--name-only")
        if "--" in rest:
            paths += rest[rest.index("--") + 1 :]
    bad = sorted({f"{p} ({why})" for p in paths if (why := forbidden_path(p))})
    if bad:
        return (
            "these files must never be committed: "
            + "; ".join(bad[:10])
            + ". Safe: `git restore --staged <file>`, then stage files by name."
        )
    return None


def check_rm(w: list[str], cwd: Path, project: Path) -> str | None:
    if not w:
        return None
    cmd = base(w[0])
    args = w[1:]
    if cmd == "rm":
        short = "".join(a[1:] for a in args if a.startswith("-") and not a.startswith("--"))
        long = {a for a in args if a.startswith("--")}
        if not (("r" in short.lower() or "--recursive" in long) and ("f" in short or "--force" in long)):
            return None
    elif cmd in ("remove-item", "ri", "del", "erase", "rd", "rmdir"):
        low = [a.lower() for a in args]
        if not (any(a.startswith("-r") for a in low) and any(a.startswith("-fo") for a in low)):
            return None
    else:
        return None
    targets = [a for a in args if not a.startswith("-")] or ["."]
    roots = allowed_roots(project)
    for t in targets:
        if "$" in t or "%" in t or t.startswith("~") or "`" in t:
            return (
                f"recursive force-delete of `{t}`: the path is not literal, so it cannot be "
                "checked to be inside the working tree. Safe: give a literal path inside the "
                "repo, or ask the owner."
            )
        where = resolve(t, cwd)
        if where == project.resolve() or not inside(where, roots):
            return (
                f"recursive force-delete outside the working tree (`{t}` -> {where}). Safe: "
                "delete only paths inside the repo (never the repo root itself); ask the "
                "owner for anything else."
            )
    return None


def check_env_read(w: list[str]) -> str | None:
    if not w or base(w[0]) not in ENV_READERS:
        return None
    for a in w[1:]:
        name = base(a)
        if name.startswith(".env") and name != ".env.example":
            return (
                f"reading `{a}` would print API keys: never read or print .env files. Safe: "
                "read .env.example for the variable names; ask the owner to check a value."
            )
    return None


def free_ram_gb() -> float | None:
    try:
        if sys.platform == "win32":
            import ctypes

            class MemStatus(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("sullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            m = MemStatus()
            m.dwLength = ctypes.sizeof(MemStatus)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
            return float(m.ullAvailPhys) / 2**30
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemAvailable:"):
                return int(line.split()[1]) / 2**20
    except Exception:  # a warning helper must never break the hook
        return None
    return None


def free_disk_gb(project: Path) -> float | None:
    try:
        return shutil.disk_usage("C:\\" if sys.platform == "win32" else str(project)).free / 2**30
    except OSError:
        return None


def check_resources(
    command: str,
    project: Path,
    ram: Callable[[], float | None] = free_ram_gb,
    disk: Callable[[Path], float | None] = free_disk_gb,
) -> str | None:
    if not HEAVY.search(strip_heredocs(command)):
        return None
    notes = []
    r, d = ram(), disk(project)
    if r is not None and r < RAM_WARN_GB:
        notes.append(f"free RAM {r:.1f} GB (under {RAM_WARN_GB:.0f} GB)")
    if d is not None and d < DISK_WARN_GB:
        notes.append(f"free disk {d:.1f} GB (under {DISK_WARN_GB:.0f} GB: stop and tell the owner)")
    if not notes:
        return None
    return (
        "heavy command with low resources: " + "; ".join(notes) + ". One heavy session at a "
        "time on this 15 GB laptop: wait, or stop something first."
    )


# ---------------------------------------------------------------- entry point


def evaluate(
    command: str, cwd: Path, project: Path, powershell: bool = False
) -> tuple[str | None, str | None]:
    """(block reason, warning). A block reason means the command must not run."""
    here = cwd
    for seg in split_commands(command):
        w = strip_prefix(words(seg, powershell))
        if not w:
            continue
        if w[0].lower() in ("cd", "set-location", "sl", "pushd", "chdir") and len(w) > 1:
            here = resolve(w[-1], here)
            continue
        reason = check_docker(w) or check_rm(w, here, project) or check_env_read(w)
        g = git_args(w)
        if not reason and g is not None:
            reason = check_git_push(g, here) or check_git_stage(g, here)
        if reason:
            return reason, None
    return None, check_resources(command, project)


def main() -> int:
    try:
        data = json.loads(sys.stdin.read() or "{}")
        tool = data.get("tool_name")
        if tool not in ("Bash", "PowerShell"):
            return 0
        command = str((data.get("tool_input") or {}).get("command") or "")
        cwd = to_path(str(data.get("cwd") or os.getcwd()))
        project = to_path(os.environ.get("CLAUDE_PROJECT_DIR") or str(cwd))
        block, warn = evaluate(command, cwd, project, powershell=tool == "PowerShell")
    except Exception as exc:  # fail closed, and say why
        print(f"guard hook error ({type(exc).__name__}: {exc}); command not run.", file=sys.stderr)
        return 2
    if block:
        print(f"Blocked by .claude/hooks/guard.py: {block}", file=sys.stderr)
        return 2
    if warn:
        print(json.dumps({"systemMessage": f"Warning (.claude/hooks/guard.py): {warn}"}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
