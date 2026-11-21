"""Gazetteer lookups over app/ingest/data/locations.yaml."""

from dataclasses import dataclass
from functools import cache
from pathlib import Path

import yaml

_DATA = Path(__file__).parent / "data" / "locations.yaml"


@dataclass(frozen=True)
class Gazetteer:
    worldwide: frozenset[str]
    countries: dict[str, str]  # alias -> code
    cities: dict[str, str]  # city -> code
    us_state_names: frozenset[str]
    us_state_abbreviations: frozenset[str]
    regions: dict[str, frozenset[str]]  # region phrase -> codes
    codes: frozenset[str]


@cache
def gazetteer() -> Gazetteer:
    raw = yaml.safe_load(_DATA.read_text(encoding="utf-8"))
    countries = {alias: code for code, aliases in raw["countries"].items() for alias in aliases}
    cities = {city: code for code, names in raw["cities"].items() for city in names}
    return Gazetteer(
        worldwide=frozenset(raw["worldwide"]),
        countries=countries,
        cities=cities,
        us_state_names=frozenset(raw["us_states"]["names"]),
        us_state_abbreviations=frozenset(raw["us_states"]["abbreviations"]),
        regions={name: frozenset(codes) for name, codes in raw["regions"].items()},
        codes=frozenset(raw["countries"]),
    )


def country_code(name: str) -> str | None:
    """ISO code for a country name, alias or code, or None."""
    key = name.strip().lower()
    if not key:
        return None
    g = gazetteer()
    if key.upper() in g.codes:
        return key.upper()
    return g.countries.get(key)
