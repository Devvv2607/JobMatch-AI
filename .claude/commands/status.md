---
description: Project status in one screen (containers, judge labels, RAM/disk, branch, CI, last ingest)
allowed-tools: Bash(python .claude/scripts/status.py), PowerShell(python .claude\scripts\status.py)
---

Run `python .claude/scripts/status.py` from the repo root (read-only) and show its output
as it is, in a code block.

Then add at most three lines under it, only where something needs attention:
- free disk under 15 GB: say "STOP: under 15 GB free on C:" (CLAUDE.md rule);
- free RAM under 2 GB: say what is using it is unknown and suggest the owner check
  Task Manager before anything heavy;
- a failed or running CI run, a judge or ingest that looks stuck, or a branch behind
  origin/main.

Tell the owner they can run the same thing in PowerShell:
`python .claude\scripts\status.py`

Do not start, stop or change anything.
