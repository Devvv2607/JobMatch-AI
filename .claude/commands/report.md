---
description: The current state in the fixed report format (Results / Decisions needed / Risks / Next)
---

Report the current state of the work in this exact format, and nothing else:

## Results
What is done and verified, each with its evidence: command run and real output, file
path, commit, PR or CI link. Numbers only if measured in the repo, with their source
(LLM-judged numbers say "LLM-judged (Gemini)"). Mark anything not verified as such.

## Decisions needed
Numbered questions only the owner can answer, each with your recommendation and what
it changes. "None" if none.

## Risks
What could go wrong or is unknown: heavy runs pending (runtime estimate), resources
(run `python .claude/scripts/status.py` for RAM, disk and containers), data changes
without a fresh `make backup`, failing or pending CI, scope creep.

## Next
The next one to three steps, and which of them wait for the owner.

Gather facts first (git status and log, CI with `gh pr checks` or `gh run list`, the
status script). Do not start, stop or change anything to write the report.
