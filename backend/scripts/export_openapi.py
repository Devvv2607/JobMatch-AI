"""Prints the OpenAPI schema. The frontend's TypeScript types are generated from it.

Usage: python -m scripts.export_openapi > ../frontend/openapi.json
"""

import json
import sys

from app.main import app

json.dump(app.openapi(), sys.stdout, indent=2, sort_keys=True)
sys.stdout.write("\n")
