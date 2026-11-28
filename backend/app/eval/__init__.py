"""Phase 4 evaluation: fictional profiles, judged pairs, the labelling tool and metrics.

Data lives in the repository's eval/ folder (mounted at /eval in the containers):
eval/profiles/*.yaml (the 25 fictional profiles) and eval/labels/<set>/ (pairs.jsonl,
judge.jsonl, plan.json, human.jsonl). See docs/briefs/phase-4.md.
"""

from pathlib import Path

# backend/app/eval/__init__.py -> the repository root is three levels up; in the
# containers the backend is /app, so this is /eval (compose mounts ./eval there).
EVAL_DIR = Path(__file__).resolve().parents[3] / "eval"
