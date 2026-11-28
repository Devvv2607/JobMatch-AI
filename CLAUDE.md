# JobMatch AI: rules for working in this repo

The standing rules, stated once. The repo enforces what it can (`.claude/hooks/guard.py`,
`.claude/settings.json`, CI); the rest is on whoever works here. When a rule and a
request conflict, say so and ask: don't pick one silently.

## Where things are
- `PLAN.md`: what gets built, the architecture, the phases.
- `docs/briefs/`: one brief per phase (and backlogs). Every phase starts from one.
- `docs/decisions/log.md`: one line per decision, dated. ADRs: `docs/decisions/000N-*.md`.
- `eval/README.md`: the evaluation (label sets, judges, `make eval`, `make eval-final`).
- `docs/claims.md`: how results may be stated publicly; `docs/bench/`: measurements.
- `.claude/commands/`: `/status`, `/phase-start <n>`, `/pre-pr`, `/report`.
  `.claude/agents/`: `reviewer`, `claims-checker`.

## Money, data and secrets
- **Free tools only.** Free tiers, open source, local models. Nothing that needs a card.
- **Personal data never goes to Gemini** (ADR 0001). Every LLM call declares
  `data_class`: `personal` goes to Groq, then Ollama only; `public` goes to Groq, then
  Gemini, then Ollama. The policy lives in code (`app/core/llm/types.py`), not config.
  `eval/private/` (the owner's real resume) is personal.
- **API keys:** never ask for one in chat, never print or read one (`.env*` reads are
  blocked). Say which variable a feature needs; the owner edits `.env`.
- **Never commit** `.env*` (only `.env.example`), `eval/private/**`, `backups/**`, real
  resumes, or any personal data. A `.pdf`/`.docx` is allowed only as a fictional fixture
  in `backend/tests/fixtures/resumes/`. The guard blocks `git add`/`commit` of these, and
  CI runs `python .claude/scripts/forbidden_files.py`.

## Data and long runs
- **`make backup` before anything that changes data**: ingest, re-embed, migrations that
  touch rows, label rewrites, imports.
- **State a runtime estimate before every experiment, benchmark or long run.** More than
  5 minutes of full CPU needs the owner's OK first. Cap full-CPU load runs at 5 minutes;
  if the machine shuts down during one, stop and report rather than retrying.
- **Disk:** check free space on C: before builds, benchmarks and long runs. **Under 15 GB
  free: stop and tell the owner.** (2026-11-21: a full C: corrupted Docker's disk.) After
  a disk-full crash, look for zero-length files in images and rebuild with `--no-cache`.
- **One heavy session at a time.** The laptop has 15 GB of RAM; Docker's WSL VM is capped
  at 6 GB (leave it). Heavy means Docker builds, model loads (ingest, embedding, eval,
  benchmarks, tests in the image), dev servers, `next build` and Playwright. Check free
  RAM first (`/status`); the guard warns under 2 GB. Another project's container
  (`ramppai-weaviate-1`) shares the Docker host: not ours, don't touch it.
- **Long jobs run as detached, named containers**, never in this session's background
  shells (Claude Code reaps those under memory pressure). Follow them with
  `docker logs -f <name>`. They wait by **polling the wall clock** (every few minutes,
  with a heartbeat line), never one long sleep: laptop sleep pauses the Docker VM's
  clock. Example: `app/eval/until_done.py`. Commit long work incrementally.
- **Outages:** if Docker is down, copy `%LOCALAPPDATA%\Docker\log` and check Windows
  System events 41/6008/42 (and 506/507/107 for sleep) before restarting anything. The
  host has had unclean shutdowns with and without load; the cause is unconfirmed.

## Numbers and claims
- **Never report a number that wasn't measured in the repo.** Every number names its
  source file and the command that made it.
- Relevance is **"LLM-judged (Gemini)"**. There are no human labels: never write
  "human-validated", "ground truth" or "accuracy". Kappa is agreement between LLM judges.
- An improvement needs a paired CI that excludes 0. Name the mode (query or profile),
  the subset and the judge. Public claims follow `docs/claims.md` ("Rules for every
  claim"); the `claims-checker` agent audits them.

## Git, PRs and CI
- **`main` is protected:** pull requests only, squash-merged by the owner. Never push to
  `main`, never force-push, never merge a PR yourself.
- **Don't rename the three required CI jobs:** `Backend (lint, types, tests, audit)`,
  `Frontend (lint, types, build, audit)`, `Docker images build, model tests in the
  image`. The `protect-main` ruleset matches them by exact name; a rename blocks every
  merge. If one ever must change, call it out at the top of the PR.
- Local green is not proof: `make test` inherits the owner's `.env` through Compose,
  CI has none. Test defaults against `Settings.model_fields[...].default`, or run with
  `-e VAR=<default>`. CI is the merge gate.
- Docker eval targets mount the current code (`EVAL_RUN` in the Makefile); images bake
  code in, so rebuild only when dependencies change.

## How a phase runs
1. Start from its brief (`/phase-start <n>`): branch `phase-<n>-<name>` from an
   up-to-date `main`, list the brief's open decisions, wait for answers.
2. Own the phase end to end. Record small decisions as one line in
   `docs/decisions/log.md`. Stop mid-phase only for a schema change, a public API
   change, or a number the owner will quote.
3. Before the PR: `/pre-pr` (reviewer, claims checker, tests, lint, typecheck, forbidden
   files). Open the PR with `gh`, wait for CI green, then **stop for review**.

## Report format
Every report to the owner uses these four headings (`/report` writes one):
- **Results**: what is done, with evidence (commands and real output, commits, links).
- **Decisions needed**: numbered, each with a recommendation.
- **Risks**: what could go wrong or is unknown.
- **Next**: the next steps, and which wait for the owner.
Evidence, not summary: say what isn't done and what you're unsure about.

## Windows
- The owner runs **PowerShell**: give commands they should run in PowerShell syntax
  (`;` not `&&`, `$env:VAR`, backslash paths). Claude's Bash tool is Git Bash.
- In Git Bash, `MSYS_NO_PATHCONV=1` stops container paths being rewritten.
- Scripted edits: Windows Python writes CRLF and heredocs can turn `"\n"` into real
  newlines. Prefer the Edit tool; otherwise write bytes, and check `grep -c $'\r'`.
- Host-only mypy noise: 3 `resource` errors in `app/ingest/runner.py` (Unix module).

## Guard rails (what the hook blocks)
`.claude/hooks/guard.py` runs before every Bash and PowerShell command. It also checks the
commands inside `bash -c` and `powershell -Command`. It blocks:
- `docker compose down`, `make down`/`reset`, `docker * prune`, `docker volume rm`,
  `--remove-orphans`;
- printing secrets: reading `.env*`, `docker compose config`, and `env` in containers;
- `git push` to main and any force push;
- recursive deletes outside the tree, of the repo root, or of `backups/`,
  `eval/private/`, `eval/labels/` or `eval/snapshots/`; `git clean -x`;
- staging or committing forbidden files.

It warns on heavy commands when RAM is under 2 GB or disk under 15 GB. Each block message
gives the safe alternative.

Failure modes:
- an error inside the guard, or Python missing from PATH, blocks the command;
- a hook timeout (60 s) or the Windows Store `python` stub lets the command through.

Tests: `python -m pytest .claude/hooks -q -p no:cacheprovider` (also run in CI). Don't
weaken a rule to get a command through; ask the owner.
