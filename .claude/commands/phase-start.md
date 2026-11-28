---
description: Start a phase from its brief - check main, create the branch, list open decisions, stop
argument-hint: <phase, e.g. 5c>
---

Start phase `$ARGUMENTS`. Do these steps in order and stop at the end. Do not write code.

1. **Brief.** Find the brief: `docs/briefs/phase-$ARGUMENTS.md` (if it is not on main, look
   on other branches with `git log --all --oneline -- docs/briefs/phase-$ARGUMENTS.md` and
   say where it lives). If no brief exists, stop: every phase starts from a brief, so ask
   the owner for one.
2. **Clean start.** `git status --porcelain` must be empty; otherwise stop and list what
   is uncommitted.
3. **Main is current.** `git fetch origin`, `git checkout main`, `git pull --ff-only`.
   Report the commit main is at.
4. **Branch.** Create `phase-$ARGUMENTS-<short-name>` from main, the name taken from the
   brief's title (lowercase, hyphens). If the branch already exists locally or on origin,
   stop and ask instead of reusing it.
5. **Read the whole brief.** Then report, in the CLAUDE.md report format:
   - **Results**: branch created, main commit, the brief's goal in two lines;
   - **Decisions needed**: every open question, "TBD", "owner decides", option list or
     unstated threshold in the brief, numbered, each with your recommendation;
   - **Risks**: heavy steps (runtime estimate; anything over 5 min of full CPU needs the
     owner's OK), data changes (`make backup` first), anything touching main's CI jobs;
   - **Next**: the first step you would take once the decisions are answered.

Stop there and wait for the owner.
