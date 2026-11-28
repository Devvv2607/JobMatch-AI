---
description: Before a PR - reviewer agent, claims checker, tests, lint, typecheck, forbidden files, PR description draft
---

Run the pre-PR checks on the current branch against `origin/main`. Report every step's
real output (shortened), never a summary of what it "should" show.

1. **Scope.** `git fetch origin`, then `git diff --stat origin/main...HEAD` and
   `git status --porcelain`. Note uncommitted changes (they are not in the PR).
2. **Forbidden files.** `python .claude/scripts/forbidden_files.py` (exit 1 = found).
   Any hit stops the PR until it is removed from the branch.
3. **Reviewer.** Run the `reviewer` agent on the branch (it reads the diff with no
   prior context). Keep its findings as it ranks them.
4. **Claims.** If the diff touches `docs/claims.md`, `eval/report.md`,
   `docs/decisions/*.md`, `eval/reports/` or README numbers, run the `claims-checker`
   agent. Otherwise say "no claims changed" and skip it.
5. **Checks**, choosing by what changed (say which you ran and why):
   - hook or script changes (`.claude/`): `python -m pytest .claude/hooks -q -p no:cacheprovider`;
   - backend: in `backend/`, `.venv/Scripts/python -m ruff check . && .venv/Scripts/python -m ruff format --check .`,
     `.venv/Scripts/python -m mypy app tests scripts` (on Windows the 3 `resource` errors in
     `app/ingest/runner.py` are host-only; CI runs Linux), and the fast tests
     `.venv/Scripts/python -m pytest -q -m "not slow" -x` or `make test` (Docker:
     estimate the runtime first);
   - frontend: `make fe-check` (estimate first; check free RAM);
   - docs only: none beyond 2 and 4.
6. **CI job names.** `git diff origin/main...HEAD -- .github/workflows/` must not rename
   `Backend (lint, types, tests, audit)`, `Frontend (lint, types, build, audit)` or
   `Docker images build, model tests in the image` (they are main's required checks).
7. **PR description draft** (do not open the PR): what changed and why; results with
   measured numbers only (LLM-judged wording); what is not in it; the decision-log lines
   added; and the attribution line.

Finish with the CLAUDE.md report format: Results / Decisions needed / Risks / Next.
