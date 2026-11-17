"""Prompts live in versioned files: app/prompts/<name>/v<N>.md.

The file holds instructions only. Untrusted text (job descriptions, resumes) is passed
separately as the user message and never formatted into these files.
"""

from dataclasses import dataclass
from functools import cache
from pathlib import Path

PROMPTS_DIR = Path(__file__).resolve().parents[2] / "prompts"


@dataclass(frozen=True)
class Prompt:
    name: str
    version: int
    system: str


@cache
def load_prompt(name: str, version: int, prompts_dir: Path = PROMPTS_DIR) -> Prompt:
    path = prompts_dir / name / f"v{version}.md"
    return Prompt(name=name, version=version, system=path.read_text(encoding="utf-8").strip())
