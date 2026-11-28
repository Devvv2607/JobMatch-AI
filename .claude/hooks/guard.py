"""PreToolUse guard for Bash and PowerShell commands (see CLAUDE.md, "Guard rails").

Claude Code sends the tool call as JSON on stdin. Exit 2 with a message on stderr blocks
the call and the message goes back to Claude; exit 0 lets it run (with a warning printed
as JSON on stdout when resources are low). Standard library only; Windows and Linux.

Blocks:
- docker compose down, `make down` / `make reset`, docker * prune, docker volume rm,
  `compose rm -v`, any docker command with --remove-orphans;
- printing secrets: reading .env files (except .env.example), `docker compose config`
  (it fills in the keys), env/printenv inside containers, and inline code that opens a
  .env file;
- git push to main, and every force push (--force, -f, --force-with-lease, +refspec);
- recursive deletes (rm -r, Remove-Item -Recurse) outside the working tree (Claude Code's
  scratch space under the temp dir is allowed), of the repo root, of a path that is not
  literal, or of the data folders backups/, eval/private/, eval/labels/, eval/snapshots/
  and .env files; `git clean` with -x/-X;
- git add / git commit that would stage or commit .env*, eval/private/**, backups/**,
  or a .pdf/.docx outside backend/tests/fixtures/resumes/ (synthetic resumes only).
Commands inside `bash -c`, `sh -c`, `powershell -Command` and `( ... )` are checked too.
Bash heredoc bodies and PowerShell here-strings are data (file text, commit messages)
and are not checked, unless the heredoc feeds a shell or interpreter, or never ends.

Warns (never blocks) when free RAM < 2 GB or free disk < 15 GB before a Docker build,
a model load (ingest, embedding, eval, benchmarks, tests in the image) or Playwright.

Failure modes: an error inside this script blocks the command (exit 2, with the reason).
If Python itself cannot start, the hook command in .claude/settings.json blocks instead.
If the hook times out, Claude Code treats it as a non-blocking error: the git calls here
are capped at 8 s each to stay well inside the 60 s hook timeout.
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
from collections.abc import Callable, Iterator
from pathlib import Path, PurePosixPath

RAM_WARN_GB = 2.0
DISK_WARN_GB = 15.0
GIT_TIMEOUT = 8
RESUME_DIR = "backend/tests/fixtures/resumes/"
PROTECTED_DIRS = ("backups", "eval/private", "eval/labels", "eval/snapshots")

HEREDOC = re.compile(r"(?<!<)<<-?(?!<)\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1")
PS_HERESTRING = re.compile(r"@(['\"])\r?\n.*?\r?\n\1@", re.S)
ENV_READERS = {
    "cat", "head", "tail", "less", "more", "type", "get-content", "gc", "grep", "rg",
    "sed", "awk", "source", ".", "strings", "xxd", "od", "base64", "select-string",
    "sls", "bat", "nl", "cut", "sort", "uniq", "diff", "findstr", "egrep", "fgrep",
    "copy", "cp", "scp", "curl",
}
SHELLS = {"bash", "sh", "zsh", "dash", "pwsh", "powershell", "powershell.exe", "pwsh.exe", "cmd"}
INTERPRETERS = {"python", "python3", "py", "python.exe", "node", "perl", "ruby"}
DOCKER = {"docker", "docker.exe", "docker-compose", "docker-compose.exe"}
DOCKER_GLOBAL_WITH_VALUE = {"--context", "-c", "-H", "--host", "--config", "-l", "--log-level"}
COMPOSE_OPTS_WITH_VALUE = {
    "-f", "--file", "-p", "--project-name", "--env-file", "--profile",
    "--project-directory", "--ansi", "--parallel", "--progress",
}
COMMIT_OPTS_WITH_VALUE = {
    "-m", "--message", "-F", "--file", "-C", "--reuse-message", "-c", "--reedit-message",
    "-t", "--template", "--author", "--date", "--fixup", "--squash", "--cleanup",
    "--trailer", "--pathspec-from-file",
}
HEAVY = re.compile(
    r"docker\s+(compose\s+)?build|docker\s+compose\s+up\b.*--build|\bmake\s+(up|ingest|"
    r"ingest-embed|bench-search|test|test-all|eval|eval-final|bm25|discover)\b|"
    r"app\.ingest\.cli\s+(run|embed)|app\.eval\.cli\s+(gate|pool|report|final)|"
    r"scripts\.bench_search|playwright|shoot\.mjs|\bnext\s+build\b|"
    r"npm\s+(--prefix\s+\S+\s+)?run\s+build",
    re.I,
)

SAFE_DOWN = (
    "`docker compose down` (and `make down` / `make reset`, which run it) stops and removes "
    "every service (db, redis, worker) and the restart settings set on them; `-v` / `make "
    "reset` also deletes the database volume. Safe: `docker compose stop <service>` for "
    "one service, or ask the owner first."
)
SAFE_PRUNE = (
    "prune deletes images, containers, volumes or build cache for every project on this "
    "Docker host. Safe: remove one named image or container you have checked, or ask the "
    "owner (disk cleanup is their call)."
)
SAFE_VOLUME = (
    "this deletes data volumes (the database lives in one). Safe: `make backup` and ask "
    "the owner; never remove a volume yourself."
)
SAFE_ORPHANS = (
    "--remove-orphans deletes containers compose does not define, including the detached "
    "judge containers (jm-judge-*) and other projects' containers. Safe: leave orphans "
    "alone, or `docker stop <name>` / `docker rm <name>` one you have checked."
)
SAFE_SECRETS = (
    "this would print API keys into the transcript. Never read or print .env values. "
    "Safe: read .env.example for variable names; `docker compose config --services` to "
    "list services; ask the owner to check a value."
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


def strip_data(command: str) -> str:
    """Drop text that is data, not commands: PowerShell here-strings, and Bash heredoc
    bodies, unless the heredoc feeds a shell or interpreter, or has no terminator."""
    command = PS_HERESTRING.sub("''", command)
    lines = command.split("\n")
    out: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        out.append(line)
        i += 1
        m = HEREDOC.search(line)
        if not m:
            continue
        head = line[: m.start()].split()
        feeds_code = bool(head) and base(head[-1]) in SHELLS | INTERPRETERS
        end = next((j for j in range(i, len(lines)) if lines[j].strip() == m.group(2)), None)
        if feeds_code or end is None:
            continue  # check the body as commands
        i = end + 1
    return "\n".join(out)


def split_commands(command: str) -> list[str]:
    """Split on ; && || | & and newlines, but not inside quotes."""
    text = strip_data(command)
    parts: list[str] = []
    buf: list[str] = []
    quote: str | None = None
    i = 0
    while i < len(text):
        ch = text[i]
        if quote:
            buf.append(ch)
            if ch == quote:
                quote = None
            elif ch == "\\" and quote == '"' and i + 1 < len(text):
                buf.append(text[i + 1])
                i += 1
        elif ch in "'\"":
            quote = ch
            buf.append(ch)
        elif ch == "&" and (text[i - 1 : i] in (">", "<") or text[i + 1 : i + 2] == ">"):
            buf.append(ch)  # a redirect (2>&1, &>), not a separator
        elif ch in ";|&\n":
            parts.append("".join(buf))
            buf = []
            if text[i : i + 2] in ("&&", "||"):
                i += 1
        else:
            buf.append(ch)
        i += 1
    parts.append("".join(buf))
    return [p.strip() for p in parts if p.strip()]


def words(segment: str, powershell: bool = False) -> list[str]:
    segment = segment.strip()
    while segment[:1] in "({" and segment:
        segment = segment[1:].strip()
    while segment[-1:] in ")}" and segment:
        segment = segment[:-1].strip()
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
    while i < len(w) and w[i] in ("sudo", "command", "exec", "time", "nohup", "&", "!"):
        i += 1
    return w[i:]


def base(word: str) -> str:
    return PurePosixPath(word.replace("\\", "/")).name.lower()


def expand_temp(text: str) -> str:
    tmp = tempfile.gettempdir()
    for var in ("$env:TEMP", "$env:TMP", "${TMPDIR}", "$TMPDIR", "$TEMP", "$TMP"):
        if text.startswith(var):
            return tmp + text[len(var) :]
    if sys.platform == "win32" and (text == "/tmp" or text.startswith("/tmp/")):
        return tmp + text[4:]  # Git Bash's /tmp is the user's temp dir
    return text


def to_path(text: str) -> Path:
    """A shell path as this OS sees it. Git Bash's /c/Users/... is C:/Users/... on
    Windows; a Windows drive path on Linux is treated as absolute (and so outside)."""
    text = expand_temp(text)
    if sys.platform == "win32":
        m = re.match(r"^/([a-zA-Z])(/.*)?$", text)
        if m:
            return Path(f"{m.group(1).upper()}:{m.group(2) or '/'}")
    elif re.match(r"^[A-Za-z]:[\\/]", text):
        return Path("/" + text[0].lower() + "/" + text[3:].replace("\\", "/"))
    else:
        text = text.replace("\\", "/")  # PowerShell-style separators, as on Windows
    return Path(text)


def resolve(text: str, cwd: Path) -> Path:
    p = to_path(text)
    return (p if p.is_absolute() else cwd / p).resolve()


def literal(text: str) -> bool:
    t = expand_temp(text)
    return not ("$" in t or "%" in t or t.startswith("~") or "`" in t)


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
            ["git", *args], cwd=cwd, capture_output=True, text=True,
            timeout=GIT_TIMEOUT, check=False,
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


def check_make(w: list[str]) -> str | None:
    if w and base(w[0]) in ("make", "make.exe", "mingw32-make"):
        targets = [a for a in w[1:] if not a.startswith("-") and "=" not in a]
        if any(t in ("down", "reset") for t in targets):
            return SAFE_DOWN
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
    i = 0
    while i < len(rest) and rest[i].startswith("-"):  # docker's global options
        i += 2 if rest[i] in DOCKER_GLOBAL_WITH_VALUE else 1
    rest = rest[i:]
    if rest[:1] == ["compose"]:
        i = 1
        while i < len(rest) and rest[i].startswith("-"):
            i += 2 if rest[i] in COMPOSE_OPTS_WITH_VALUE else 1
        sub, args = (rest[i], rest[i + 1 :]) if i < len(rest) else ("", [])
        if sub == "down":
            return SAFE_DOWN
        if sub == "config" and not any(
            a in ("--services", "--volumes", "--profiles", "--images", "-q", "--quiet")
            for a in args
        ):
            return SAFE_SECRETS
        if sub == "rm" and any(a in ("-v", "--volumes") or (a.startswith("-") and not a.startswith("--") and "v" in a) for a in args):
            return SAFE_VOLUME
        if sub in ("exec", "run") and any(base(a) in ("env", "printenv") for a in args):
            return SAFE_SECRETS
        return None
    if len(rest) >= 2 and rest[1] == "prune" and rest[0] in (
        "system", "volume", "image", "container", "builder", "network", "buildx",
    ):
        return SAFE_PRUNE
    if len(rest) >= 2 and rest[0] == "volume" and rest[1] in ("rm", "remove"):
        return SAFE_VOLUME
    if rest[:1] == ["exec"] and any(base(a) in ("env", "printenv") for a in rest[1:]):
        return SAFE_SECRETS
    if rest[:1] == ["rm"] and any("$(" in a or "`" in a for a in w):
        return (
            "`docker rm` of a computed list removes every matching container, including other "
            "projects' and the judge containers. Safe: `docker rm <name>` for each one you "
            "have checked."
        )
    return None


def git_args(w: list[str], cwd: Path) -> tuple[list[str], Path] | None:
    """(arguments after `git` and its global options, directory it runs in), or None."""
    if not w or base(w[0]) not in ("git", "git.exe"):
        return None
    i, where = 1, cwd
    while i < len(w) and w[i].startswith("-"):
        if w[i] == "-C" and i + 1 < len(w):
            where = resolve(w[i + 1], where)
            i += 2
        elif w[i] == "-c":
            i += 2
        else:
            i += 1
    return w[i:], where


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
    current = run_git(cwd, "rev-parse", "--abbrev-ref", "HEAD")[:1]
    dests = [r.split(":")[-1] for r in refspecs] if refspecs else current
    if any(d in ("main", "refs/heads/main") for d in dests):
        return SAFE_MAIN
    if "HEAD" in refspecs and current == ["main"]:
        return SAFE_MAIN
    return None


def check_git_clean(args: list[str]) -> str | None:
    if args[:1] == ["clean"] and any(
        a.startswith("-") and not a.startswith("--") and ("x" in a or "X" in a) for a in args[1:]
    ):
        return (
            "`git clean -x` also deletes ignored files: .env, backups/, eval/private/ and the "
            "judge label files. Safe: `git clean -n` to see what would go, then delete named "
            "paths; or `git clean -fd` (untracked, not ignored)."
        )
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
        if "--all" in rest or any("a" in s[1:] for s in short if s not in COMMIT_OPTS_WITH_VALUE):
            paths += run_git(cwd, "diff", "--name-only")
        i = 0
        while i < len(rest):  # pathspecs: positional words not taken by an option
            a = rest[i]
            if a == "--":
                paths += rest[i + 1 :]
                break
            if a in COMMIT_OPTS_WITH_VALUE:
                i += 2
                continue
            if not a.startswith("-"):
                paths.append(a)
            i += 1
    bad = sorted({f"{p} ({why})" for p in paths if (why := forbidden_path(p))})
    if bad:
        return (
            "these files must never be committed: "
            + "; ".join(bad[:10])
            + ". Safe: `git restore --staged <file>`, then stage files by name."
        )
    return None


def check_rm(w: list[str], cwd: Path | None, project: Path) -> str | None:
    if not w:
        return None
    cmd = base(w[0])
    args = w[1:]
    if cmd == "rm":
        short = "".join(a[1:] for a in args if a.startswith("-") and not a.startswith("--"))
        if not ("r" in short.lower() or "--recursive" in args):
            return None
    elif cmd in ("remove-item", "ri", "del", "erase", "rd", "rmdir", "rm.exe"):
        low = [a.lower() for a in args]
        if not any(a.startswith("-r") for a in low):
            return None
    else:
        return None
    targets = [
        a for a in args if not a.startswith("-") and a.lower() not in ("$true", "$false")
    ] or ["."]
    roots = allowed_roots(project)
    root = project.resolve()
    for t in targets:
        if cwd is None or not literal(t):
            return (
                f"recursive delete of `{t}`: the path (or the directory it is relative to) is "
                "not literal, so it cannot be checked to be inside the working tree. Safe: "
                "give a literal path inside the repo, or ask the owner."
            )
        where = resolve(t, cwd)
        if where == root or not inside(where, roots):
            return (
                f"recursive delete outside the working tree (`{t}` -> {where}). Safe: delete "
                "only paths inside the repo (never the repo root itself); ask the owner for "
                "anything else."
            )
        rel = where.relative_to(root).as_posix() if inside(where, [root]) else ""
        for d in PROTECTED_DIRS:
            if rel == d or rel.startswith(d + "/") or d.startswith(rel + "/"):
                return (
                    f"recursive delete of `{t}` would remove {d}/ (database dumps, private "
                    "eval data, judge labels or the frozen snapshot). Safe: ask the owner; "
                    "`make backup` first for anything data-related."
                )
        if PurePosixPath(rel).name.lower().startswith(".env"):
            return SAFE_SECRETS
    return None


def check_secrets(w: list[str]) -> str | None:
    if not w:
        return None
    cmd = base(w[0])
    if cmd in ENV_READERS:
        for a in w[1:]:
            name = base(a)
            if name.startswith(".env") and name != ".env.example":
                return f"reading `{a}`: " + SAFE_SECRETS
    if cmd in ("env", "printenv", "get-childitem", "gci", "dir", "ls") and any(
        a.lower().startswith("env:") for a in w[1:]
    ):
        return SAFE_SECRETS
    if cmd in INTERPRETERS:
        code = " ".join(w[1:])
        if re.search(r"\.env(?!\.example)(\.[A-Za-z]+)?['\"\s)]", code + " ") and re.search(
            r"(^|\s)-(c|e|m\s+dotenv)", " " + code
        ):
            return SAFE_SECRETS
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
    if not HEAVY.search(strip_data(command)):
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


def nested(w: list[str]) -> Iterator[tuple[str, bool]]:
    """Command strings run by `bash -c ...`, `powershell -Command ...` and the like."""
    if not w or base(w[0]) not in SHELLS:
        return
    ps = base(w[0]).startswith(("pwsh", "powershell"))
    for i, a in enumerate(w[1:-1], start=1):
        if a.lower() in ("-c", "-lc", "-command", "/c", "-encodedcommand"):
            yield " ".join(w[i + 1 :]), ps
            return


def evaluate(
    command: str, cwd: Path, project: Path, powershell: bool = False, depth: int = 0
) -> tuple[str | None, str | None]:
    """(block reason, warning). A block reason means the command must not run."""
    here: Path | None = cwd
    for seg in split_commands(command):
        w = strip_prefix(words(seg, powershell))
        if not w:
            continue
        if w[0].lower() in ("cd", "set-location", "sl", "pushd", "chdir"):
            target = w[-1] if len(w) > 1 else "~"
            here = resolve(target, here) if here is not None and literal(target) else None
            continue
        reason = (
            check_make(w)
            or check_docker(w)
            or check_rm(w, here, project)
            or check_secrets(w)
        )
        g = git_args(w, here or cwd)
        if not reason and g is not None:
            args, where = g
            reason = (
                check_git_push(args, where) or check_git_clean(args) or check_git_stage(args, where)
            )
        if not reason and depth < 3:
            for inner, ps in nested(w):
                reason, _ = evaluate(inner, here or cwd, project, ps, depth + 1)
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
