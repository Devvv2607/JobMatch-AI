"""Company boilerplate removal for the text that is embedded and searched.

A company's postings repeat the same paragraphs: "About us", benefits, the equal
opportunity statement, section headings. Truncated to the embedding model's 512 tokens,
that shared text dominates, so two different roles at one company embed close together.

Rule (deterministic, no LLM): split each description into paragraphs (blocks separated by
a blank line, which is how html_to_text renders block elements and list items), and drop
every paragraph whose normalised text occurs in at least `min_share` of that company's
distinct descriptions, for companies with at least `min_postings` distinct descriptions.

Counting is over *distinct* descriptions, so one role posted in ten cities (identical text)
counts once and its own paragraphs are not mistaken for boilerplate.
"""

import hashlib
import math
import re
from collections import Counter
from collections.abc import Iterable

from app.ingest.text import normalise_key

_PARAGRAPH_BREAK = re.compile(r"\n\s*\n")


def paragraphs(description: str) -> list[str]:
    """Non-empty paragraphs, stripped, in order."""
    return [p.strip() for p in _PARAGRAPH_BREAK.split(description) if p.strip()]


def _key(paragraph: str) -> str:
    return normalise_key(paragraph)


def boilerplate_keys(
    descriptions: Iterable[str], *, min_share: float, min_postings: int
) -> frozenset[str]:
    """Normalised paragraphs that occur in at least `min_share` of the distinct
    descriptions. Empty when there are fewer than `min_postings` distinct descriptions."""
    distinct: dict[str, str] = {}
    for description in descriptions:
        distinct.setdefault(hashlib.sha256(description.encode()).hexdigest(), description)
    if len(distinct) < min_postings:
        return frozenset()
    frequency: Counter[str] = Counter()
    for description in distinct.values():
        frequency.update({k for p in paragraphs(description) if (k := _key(p))})
    needed = math.ceil(min_share * len(distinct))
    return frozenset(key for key, count in frequency.items() if count >= needed)


def strip_boilerplate(description: str, boilerplate: frozenset[str]) -> str:
    """The description without its boilerplate paragraphs, paragraphs kept in order.
    Paragraphs with no letters or digits (separators) are dropped too."""
    kept = [p for p in paragraphs(description) if (k := _key(p)) and k not in boilerplate]
    return "\n\n".join(kept)
