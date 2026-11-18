"""Canonical skill taxonomy (app/ingest/data/skills.yaml) and extraction from text.

Phase 3 reuses `canonical_skill` to map candidate skills onto the same names, so
"Postgres" and "PostgreSQL" compare equal.
"""

import re
from dataclasses import dataclass
from functools import cache
from pathlib import Path

import yaml

_DATA = Path(__file__).parent / "data" / "skills.yaml"
# Word boundaries that treat + # . as part of a name, so "C++", "C#" and ".NET" work.
_BEFORE = r"(?<![\w+#.])"
_AFTER = r"(?![\w+#])"


@dataclass(frozen=True)
class Skill:
    name: str
    category: str
    pattern: re.Pattern[str]


@cache
def taxonomy() -> tuple[Skill, ...]:
    raw = yaml.safe_load(_DATA.read_text(encoding="utf-8"))
    skills = []
    for category, entries in raw.items():
        for name, spec in entries.items():
            skills.append(Skill(name, category, _compile(str(name), spec or {})))
    return tuple(skills)


@cache
def _alias_index() -> dict[str, str]:
    raw = yaml.safe_load(_DATA.read_text(encoding="utf-8"))
    index: dict[str, str] = {}
    for entries in raw.values():
        for name, spec in entries.items():
            index[str(name).lower()] = str(name)
            for alias in (spec or {}).get("aliases") or []:
                if not str(alias).startswith("re:"):
                    index[str(alias).lower()] = str(name)
    return index


def _compile(name: str, spec: dict[str, object]) -> re.Pattern[str]:
    case_sensitive = {str(s) for s in spec.get("case_sensitive") or []}  # type: ignore[attr-defined]
    alternatives: list[str] = []
    if spec.get("match_name", True):
        escaped = re.escape(name)
        alternatives.append(escaped if name in case_sensitive else f"(?i:{escaped})")
    for alias in spec.get("aliases") or []:  # type: ignore[attr-defined]
        alias = str(alias)
        if alias.startswith("re:"):
            alternatives.append(alias[3:])
        else:
            escaped = re.escape(alias).replace(r"\ ", r"[\s-]+")
            alternatives.append(escaped if alias in case_sensitive else f"(?i:{escaped})")
    return re.compile(f"{_BEFORE}(?:{'|'.join(alternatives)}){_AFTER}")


def extract_skills(text: str) -> list[str]:
    """Canonical skills mentioned in `text`, in taxonomy order."""
    return [skill.name for skill in taxonomy() if skill.pattern.search(text)]


def canonical_skill(name: str) -> str | None:
    """The canonical name for a skill or alias, e.g. "postgres" -> "PostgreSQL"."""
    return _alias_index().get(" ".join(name.lower().split()))
