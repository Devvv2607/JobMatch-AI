"""Tests for .claude/hooks/guard.py: one allowed and one blocked example (at least) per
rule, plus end-to-end runs through stdin. Run: python -m pytest .claude/hooks -q"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
import guard  # noqa: E402

HOOK = Path(__file__).parent / "guard.py"


def git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.email=t@example.invalid", "-c", "user.name=t", *args],
        cwd=repo, check=True, capture_output=True,
    )


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    r = tmp_path / "repo"
    r.mkdir()
    git(r, "init", "-q", "-b", "feature")
    (r / ".gitignore").write_text(".env\neval/private/\nbackups/\n")
    (r / "README.md").write_text("x\n")
    git(r, "add", ".gitignore", "README.md")
    git(r, "commit", "-q", "-m", "init")
    return r


def blocked(command: str, repo: Path, cwd: Path | None = None, ps: bool = False) -> str | None:
    reason, _ = guard.evaluate(command, cwd or repo, repo, powershell=ps)
    return reason


# ------------------------------------------------------------------ docker


@pytest.mark.parametrize(
    "cmd",
    [
        "docker compose down",
        "docker compose -f docker-compose.yml down -v",
        "docker-compose down",
        "cd backend && docker compose down",
        "docker system prune -af",
        "docker volume prune",
        "docker builder prune",
        "docker volume rm jobmatch_pgdata",
        "docker compose up -d --remove-orphans",
        "MSYS_NO_PATHCONV=1 docker compose run --rm --remove-orphans api true",
    ],
)
def test_docker_destructive_is_blocked(cmd: str, repo: Path) -> None:
    assert blocked(cmd, repo)


@pytest.mark.parametrize(
    "cmd",
    [
        "docker compose ps -a",
        "docker compose up -d --no-deps worker",
        "docker compose stop worker",
        "docker stop jm-judge-v3-gemini",
        "docker compose logs worker | grep down",
        "docker volume ls",
        "docker compose run --rm api python -m app.cli --cooldown",
    ],
)
def test_docker_safe_is_allowed(cmd: str, repo: Path) -> None:
    assert blocked(cmd, repo) is None


def test_heredoc_text_is_data_not_commands(repo: Path) -> None:
    cmd = "cat >> docs/log.md <<'EOF'\n- never run docker compose down\nrm -rf /\nEOF\necho ok"
    assert blocked(cmd, repo) is None


# ------------------------------------------------------------------ git push


@pytest.mark.parametrize(
    "cmd",
    [
        "git push origin main",
        "git push -u origin main",
        "git push origin HEAD:main",
        "git push origin feature:refs/heads/main",
        "git push --force",
        "git push -f origin feature",
        "git push --force-with-lease origin feature",
        "git push origin +feature",
        "git -C . push origin main",
    ],
)
def test_push_to_main_or_force_is_blocked(cmd: str, repo: Path) -> None:
    assert blocked(cmd, repo)


def test_plain_push_on_main_is_blocked(repo: Path) -> None:
    git(repo, "checkout", "-q", "-b", "main")
    assert blocked("git push", repo)
    assert blocked("git push origin", repo)
    assert blocked("git push origin HEAD", repo)


@pytest.mark.parametrize(
    "cmd", ["git push", "git push -u origin feature", "git push origin feature:feature"]
)
def test_push_of_a_branch_is_allowed(cmd: str, repo: Path) -> None:
    assert blocked(cmd, repo) is None


# ------------------------------------------------------------------ rm -rf


def test_rm_rf_inside_the_tree_is_allowed(repo: Path) -> None:
    (repo / "build").mkdir()
    assert blocked("rm -rf build", repo) is None
    assert blocked("rm -rf ./build/cache node_modules", repo) is None
    assert blocked("rm -r -f build", repo) is None
    assert blocked("rm -f notes.txt", repo) is None  # not recursive
    assert blocked("rm -r build", repo) is None  # not forced


def test_rm_rf_in_the_claude_scratch_space_is_allowed(repo: Path) -> None:
    scratch = Path(tempfile.gettempdir()) / "claude" / "session" / "scratchpad"
    assert blocked(f'rm -rf "{scratch}"', repo) is None


@pytest.mark.parametrize(
    "cmd",
    [
        "rm -rf /",
        "rm -rf ..",
        "rm -fr ../other-project",
        "rm --recursive --force /etc",
        "rm -rf ~/Documents",
        "rm -rf $HOME/x",
        "rm -rf .",  # the repo root itself
    ],
)
def test_rm_rf_outside_the_tree_is_blocked(cmd: str, repo: Path) -> None:
    assert blocked(cmd, repo)


def test_cd_outside_then_rm_rf_is_blocked(repo: Path, tmp_path: Path) -> None:
    assert blocked(f'cd "{tmp_path}" && rm -rf repo2', repo)


def test_powershell_remove_item(repo: Path) -> None:
    assert blocked(r"Remove-Item -Recurse -Force C:\Windows\Temp\x", repo, ps=True)
    assert blocked("Remove-Item -Recurse -Force build", repo, ps=True) is None
    assert blocked(r"Remove-Item C:\Users\x.txt", repo, ps=True) is None  # not recursive


@pytest.mark.skipif(sys.platform != "win32", reason="Git Bash drive paths are Windows-only")
def test_git_bash_drive_paths_are_understood(repo: Path) -> None:
    drive = str(repo.resolve())[0].lower()
    posix = "/" + drive + str(repo.resolve())[2:].replace("\\", "/")
    assert blocked(f'rm -rf "{posix}/build"', repo) is None
    assert blocked("rm -rf /c/Windows/Temp/x", repo)


# ------------------------------------------------------------------ .env reads


@pytest.mark.parametrize(
    "cmd", ["cat .env", "grep GEMINI backend/.env", "Get-Content .env.local", "type .env", "head -3 .env.production"]
)
def test_reading_env_is_blocked(cmd: str, repo: Path) -> None:
    assert blocked(cmd, repo, ps=cmd.startswith(("Get-", "type")))


@pytest.mark.parametrize("cmd", ["cat .env.example", "grep -n KEY .env.example", "ls .env"])
def test_env_example_and_listing_are_allowed(cmd: str, repo: Path) -> None:
    assert blocked(cmd, repo) is None


# ------------------------------------------------------------------ staging forbidden files


@pytest.mark.parametrize(
    "path,bad",
    [
        (".env", True),
        ("backend/.env.local", True),
        (".env.example", False),
        ("eval/private/cowork/batch-05.xlsx", True),
        ("backups/jobmatch-20261128.dump", True),
        ("docs/resume.pdf", True),
        ("frontend/public/cv.docx", True),
        ("backend/tests/fixtures/resumes/fictional-asha.pdf", False),
        ("./eval/report.md", False),
    ],
)
def test_forbidden_path(path: str, bad: bool) -> None:
    assert bool(guard.forbidden_path(path)) is bad


def test_git_add_of_forbidden_files_is_blocked(repo: Path) -> None:
    (repo / ".env").write_text("KEY=x\n")
    (repo / "eval" / "private").mkdir(parents=True)
    (repo / "eval" / "private" / "p.md").write_text("x")
    (repo / "cv.pdf").write_bytes(b"%PDF")
    assert blocked("git add .env", repo)  # named, although ignored
    assert blocked("git add -f eval/private/p.md", repo)
    assert blocked("git add .", repo)  # cv.pdf is not ignored
    assert blocked("git add -A", repo)


def test_git_add_of_normal_files_is_allowed(repo: Path) -> None:
    (repo / ".env").write_text("KEY=x\n")  # ignored, so `git add .` skips it
    (repo / "notes.md").write_text("x")
    assert blocked("git add notes.md", repo) is None
    assert blocked("git add .", repo) is None
    assert blocked("git add .env.example", repo) is None


def test_git_commit_checks_what_is_staged(repo: Path) -> None:
    (repo / "notes.md").write_text("x")
    git(repo, "add", "notes.md")
    assert blocked('git commit -m "notes"', repo) is None
    (repo / "cv.docx").write_bytes(b"PK")
    git(repo, "add", "cv.docx")
    assert blocked('git commit -m "add cv"', repo)


def test_git_commit_all_checks_tracked_changes(repo: Path) -> None:
    (repo / "cv.pdf").write_bytes(b"%PDF")
    git(repo, "add", "cv.pdf")  # staged before this rule, by hand
    git(repo, "commit", "-q", "-m", "x")
    (repo / "cv.pdf").write_bytes(b"%PDF-2")
    assert blocked('git commit -am "update"', repo)
    assert blocked('git commit -m "nothing staged"', repo) is None


# ------------------------------------------------------------------ resource warnings


def test_heavy_command_warns_on_low_ram_or_disk(repo: Path) -> None:
    low = guard.check_resources("docker compose build api", repo, lambda: 1.2, lambda _: 40.0)
    assert low and "RAM 1.2" in low
    disk = guard.check_resources("make ingest", repo, lambda: 6.0, lambda _: 9.5)
    assert disk and "disk 9.5" in disk
    assert guard.check_resources("npx playwright test", repo, lambda: 6.0, lambda _: 40.0) is None


def test_light_command_never_warns(repo: Path) -> None:
    assert guard.check_resources("git status", repo, lambda: 0.5, lambda _: 1.0) is None


# ------------------------------------------------------------------ end to end (stdin -> exit code)


def run_hook(command: str, cwd: Path, tool: str = "Bash") -> subprocess.CompletedProcess[str]:
    payload = {"tool_name": tool, "tool_input": {"command": command}, "cwd": str(cwd)}
    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(cwd)}
    return subprocess.run(
        [sys.executable, str(HOOK)], input=json.dumps(payload), capture_output=True,
        text=True, env=env, timeout=60, check=False,
    )


def test_end_to_end_block_and_allow(repo: Path) -> None:
    no = run_hook("docker compose down", repo)
    assert no.returncode == 2 and "docker compose stop" in no.stderr
    yes = run_hook("docker compose ps", repo)
    assert yes.returncode == 0 and yes.stderr == ""


def test_other_tools_are_ignored(repo: Path) -> None:
    r = subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps({"tool_name": "Read", "tool_input": {"file_path": ".env"}}),
        capture_output=True, text=True, check=False,
    )
    assert r.returncode == 0


@pytest.mark.parametrize(
    "cmd",
    [
        "sleep 1 & rm -rf /",  # background & is a separator
        "bash -c 'git push origin main'",
        "sh -c \"docker compose down\"",
        "(rm -rf /)",
        "make reset",
        "make down",
        "docker compose config",
        "docker compose exec api env",
        "docker compose run --rm api printenv",
        "docker exec jobmatch-api-1 env",
        "python -c \"print(open('.env').read())\"",
        "cd && rm -rf Documents",
        "cd ~ && rm -rf Documents",
        "rm -rf backups",
        "rm -rf eval/private",
        "rm -rf eval",  # contains eval/labels
        "rm -r eval/labels/eval-2026-11-25",  # recursive without -f still checked
        "git clean -fdx",
        "git clean -X -f",
        "docker --context default compose down",
        "docker compose rm -sfv",
        "docker rm -f $(docker ps -aq)",
        "bash <<EOF\nrm -rf /\nEOF",  # heredoc fed to a shell is code
        "echo hi <<X\nrm -rf /",  # unterminated heredoc: checked as commands
        "Remove-Item -Recurse C:\\Users\\Dev\\Documents",
    ],
)
def test_review_probes_are_blocked(cmd: str, repo: Path) -> None:
    ps = cmd.startswith("Remove-Item")
    assert blocked(cmd, repo, ps=ps), cmd


@pytest.mark.parametrize(
    "cmd",
    [
        "git commit -m 'x; cat .env too'",
        'gh pr create --body "never commit secrets; cat .env is blocked now"',
        'echo "done && docker compose down"',
        "git commit -m \"guard: docker compose down and rm -rf / are blocked\"",
        "docker compose config --services",
        "make eval",
        "pytest -q 2>&1 | tail -5",
        "cat file.txt <<<\"EOF\"",
        "git clean -fd",
        "rm -rf eval/reports/tmp",
    ],
)
def test_review_false_positives_are_allowed(cmd: str, repo: Path) -> None:
    assert blocked(cmd, repo) is None, cmd


def test_powershell_here_string_is_data(repo: Path) -> None:
    cmd = "git commit -m @'\nGuard: docker compose down is now blocked; cat .env too\n'@"
    assert blocked(cmd, repo, ps=True) is None


def test_temp_paths_expand_to_the_scratch_space(repo: Path) -> None:
    assert blocked("Remove-Item -Recurse -Force $env:TEMP\\claude\\s\\x", repo, ps=True) is None
    assert blocked("rm -rf $TMPDIR/claude/s/x", repo) is None
    assert blocked("Remove-Item -Recurse -Force $env:TEMP\\other", repo, ps=True)


def test_git_commit_pathspec_without_double_dash(repo: Path) -> None:
    (repo / "cv.pdf").write_bytes(b"%PDF")
    assert blocked("git commit -m x cv.pdf", repo)
    assert blocked("git commit -m x README.md", repo) is None


def test_git_dash_c_runs_the_check_in_that_directory(repo: Path, tmp_path: Path) -> None:
    (repo / "cv.pdf").write_bytes(b"%PDF")
    assert blocked(f'git -C "{repo}" add cv.pdf', tmp_path)


def test_drive_paths_are_absolute_on_every_platform(repo: Path) -> None:
    assert guard.to_path("C:\\Windows\\Temp").is_absolute()
    assert guard.to_path("D:/data").is_absolute()


# ------------------------------------------------------------------ the launcher (run_guard.sh)

LAUNCHER = Path(__file__).parent / "run_guard.sh"
REPO_ROOT = Path(__file__).resolve().parents[2]
SH = shutil.which("sh")
needs_sh = pytest.mark.skipif(SH is None, reason="no POSIX sh")


def launch(project: Path, command: str, path_env: str | None = None) -> subprocess.CompletedProcess[str]:
    payload = {"tool_name": "Bash", "tool_input": {"command": command}, "cwd": str(project)}
    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(project)}
    if path_env is not None:
        env["PATH"] = path_env
    return subprocess.run(
        [str(SH), str(LAUNCHER)], input=json.dumps(payload), capture_output=True, text=True,
        env=env, timeout=60, check=False,
    )


@needs_sh
@pytest.mark.skipif(
    not any((REPO_ROOT / p).exists() for p in ("backend/.venv/Scripts/python.exe", "backend/.venv/bin/python")),
    reason="no backend venv",
)
def test_launcher_uses_the_venv_and_refuses_the_probe() -> None:
    no = launch(REPO_ROOT, "cat .env.guard-selfcheck")
    assert no.returncode == 2 and "Blocked by .claude/hooks/guard.py" in no.stderr
    yes = launch(REPO_ROOT, "git status --short")
    assert yes.returncode == 0, yes.stderr


@needs_sh
def test_launcher_blocks_when_the_interpreter_is_broken(tmp_path: Path) -> None:
    for rel in ("backend/.venv/Scripts/python.exe", "backend/.venv/bin/python"):
        fake = tmp_path / rel
        fake.parent.mkdir(parents=True, exist_ok=True)
        fake.write_text("#!/bin/sh\nexit 9009\n")  # like the Store stub: exits, runs nothing
        fake.chmod(0o755)
    r = launch(tmp_path, "git status --short")
    assert r.returncode == 2
    assert "interpreter failed" in r.stderr


@needs_sh
def test_launcher_blocks_when_no_python_is_found(tmp_path: Path) -> None:
    r = launch(tmp_path, "git status --short", path_env=str(tmp_path / "empty-bin"))
    assert r.returncode == 2
    assert "no Python found" in r.stderr


def test_bad_input_fails_closed(repo: Path) -> None:
    r = subprocess.run(
        [sys.executable, str(HOOK)], input="{not json", capture_output=True, text=True, check=False
    )
    assert r.returncode == 2 and "guard hook error" in r.stderr
