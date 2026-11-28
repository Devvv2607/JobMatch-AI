#!/bin/sh
# Launches guard.py with an explicit interpreter, never whatever `python` is first on PATH
# (on Windows that can be the Microsoft Store stub, which exits without running anything
# and would silently disable the guard). Order:
#   1. the backend venv's Python (backend/.venv: Scripts/python.exe on Windows,
#      bin/python on Linux/macOS);
#   2. the Python launcher, `py -3`.
# The guard exits 0 (allow) or 2 (block). Any other result - no interpreter found, an
# interpreter that fails to start, a crash before guard.py's own error handling - blocks
# the command, so the guard can only fail closed. Claude Code pipes the tool call (JSON)
# on stdin; it passes straight through to guard.py.
dir="${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "$0")/../.." && pwd)}"
guard="$dir/.claude/hooks/guard.py"
rc=""
for py in "$dir/backend/.venv/Scripts/python.exe" "$dir/backend/.venv/bin/python"; do
  if [ -x "$py" ]; then
    "$py" "$guard"
    rc=$?
    break
  fi
done
if [ -z "$rc" ]; then
  if command -v py >/dev/null 2>&1; then
    py -3 "$guard"
    rc=$?
  else
    echo "guard hook: no Python found (backend/.venv or py -3), so the command is blocked. Fix: create the backend venv (uv sync in backend/) or install Python 3 with the py launcher." >&2
    exit 2
  fi
fi
case "$rc" in
  0|2) exit "$rc" ;;
esac
echo "guard hook: the Python interpreter failed (exit $rc), so the command is blocked. Check backend/.venv or py -3." >&2
exit 2
