"""Prints the OpenAPI schema. The frontend's TypeScript types are generated from it.

Usage: python -m scripts.export_openapi > ../frontend/openapi.json
"""

import json
import sys

from app.main import app

# LF on every OS, so the committed file is byte-identical whether exported on Windows
# or in CI.
sys.stdout.reconfigure(newline="\n")  # type: ignore[union-attr]
json.dump(app.openapi(), sys.stdout, indent=2, sort_keys=True)
sys.stdout.write("\n")
