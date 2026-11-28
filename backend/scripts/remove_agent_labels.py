"""Keep only the owner's labels in a label set's human.jsonl (2026-11-26: Claude Cowork,
an AI agent, pressed keys in the labelling tool after the owner's first labels).

    python -m scripts.remove_agent_labels --set eval-2026-11-25 --keep-first N

The first N events stay in human.jsonl; every later event moves to
human-agent-removed-aside.jsonl (kept, gitignored, never read as human labels). The
agent's grades themselves are in judge-claude-cowork.jsonl. The plan's suggested order is
made provisional again (the agent's suggested-phase label had fixed it). Run it only
with the labelling tool stopped (it keeps the log in memory); it refuses if human.jsonl
no longer matches the backup's sha256 (any key press since the backup changes it).
"""

import argparse
import hashlib
import json
import sys
from pathlib import Path

LABELS = Path("/eval/labels")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--set", required=True)
    parser.add_argument("--keep-first", type=int, required=True)
    parser.add_argument("--backup-sha256", required=True, help="sha256 of the backed-up log")
    args = parser.parse_args()
    folder = LABELS / args.set
    log = folder / "human.jsonl"
    raw = log.read_bytes()
    if hashlib.sha256(raw).hexdigest() != args.backup_sha256:
        print("human.jsonl changed since the backup: back it up again first", file=sys.stderr)
        return 1
    lines = raw.decode("utf-8").splitlines()
    keep, move = lines[: args.keep_first], lines[args.keep_first :]
    aside = folder / "human-agent-removed-aside.jsonl"
    aside.write_text("".join(x + "\n" for x in move), encoding="utf-8")
    log.write_text("".join(x + "\n" for x in keep), encoding="utf-8")
    plan_path = folder / "plan.json"
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    plan["suggested_fixed"] = False
    plan_path.write_text(json.dumps(plan, indent=1), encoding="utf-8")
    print(f"kept {len(keep)} events in {log}; moved {len(move)} to {aside}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
