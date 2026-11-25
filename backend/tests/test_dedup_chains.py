"""Chained near-duplicate groups (app/ingest/dedup.py, assign_groups): a posting joins a
group only if it also matches the group's canonical posting at INGEST_NEAR_DUPLICATE_
CANONICAL_MIN (0.85). Owner review 2026-11-25: an AlphaSense chain through a Himalayas
posting merged two different roles (Jaccard 0.447 with the kept job), while MongoDB city
variants chained at 0.88-0.89 against the kept job are the same role."""

import uuid
from datetime import UTC, datetime, timedelta
from itertools import combinations

from app.ingest.dedup import Posting, assign_groups, jaccard, match

T0 = datetime(2026, 11, 24, tzinfo=UTC)
THRESHOLD = 0.9
CANONICAL_MIN = 0.85
BASE = [f"w{i}" for i in range(100)]


def posting(
    name: str,
    word_list: list[str],
    *,
    source: str = "greenhouse",
    quality: str = "ats_direct",
    order: int = 0,
    remote: str = "unknown",
) -> Posting:
    return Posting(
        id=uuid.uuid5(uuid.NAMESPACE_DNS, name),
        source=source,
        quality=quality,
        first_seen=T0 + timedelta(hours=order),
        posted_at=None,
        location=name,
        location_norm=name,
        eligibility=("listed", ("IN",)),
        remote_policy=remote,
        words=frozenset(word_list),
    )


def groups(members: list[Posting], canonical_min: float | None) -> dict[str, str]:
    """Hidden posting -> the posting it is hidden under, by name (location)."""
    edges = [(a, b) for a, b in combinations(members, 2) if match(a, b, THRESHOLD)]
    return {d.location: c.location for d, c in assign_groups(edges, canonical_min).items()}


def test_a_chain_whose_ends_score_088_stays_one_group() -> None:
    a = posting("A", BASE[6:], order=0)  # B minus 6 words
    b = posting("B", BASE, order=1)
    c = posting("C", BASE[:6] + BASE[12:], order=2)  # B minus 6 other words
    assert jaccard(a.words, b.words) == jaccard(b.words, c.words) == 0.94
    assert jaccard(a.words, c.words) == 0.88  # below 0.90: merged only through B
    assert groups([a, b, c], CANONICAL_MIN) == {"B": "A", "C": "A"}


def test_a_chain_whose_ends_score_045_splits() -> None:
    """A Jaccard chain at >= 0.90 cannot reach 0.45 (Jaccard distance is a metric), so
    the real case is a bridge from another source whose short text is contained in both,
    as the Himalayas posting was for AlphaSense."""
    a = posting("A", BASE[:72], order=0)
    c = posting("C", BASE[27:], order=2)
    bridge = posting("H", BASE[27:72], source="himalayas", quality="aggregator_full", order=1)
    assert round(jaccard(a.words, c.words), 2) == 0.45
    assert match(a, bridge, THRESHOLD) and match(bridge, c, THRESHOLD)  # containment 1.0

    assert groups([a, bridge, c], None) == {"H": "A", "C": "A"}  # the old rule: one group
    assert groups([a, bridge, c], CANONICAL_MIN) == {"H": "A"}  # C is its own job again


def test_postings_that_leave_a_group_regroup_among_themselves() -> None:
    a = posting("A", BASE[:72], order=0)
    bridge = posting("H", BASE[27:72], source="himalayas", quality="aggregator_full", order=1)
    c = posting("C", BASE[27:], order=2)
    d = posting("D", BASE[27:99], order=3)  # C's near-copy (Jaccard 0.99)
    assert groups([a, bridge, c, d], CANONICAL_MIN) == {"H": "A", "D": "C"}


def test_identical_text_with_a_different_remote_policy_is_not_chained_in() -> None:
    """Same-source near-duplicates need the same remote policy; a chain through another
    source no longer gets around that (GitLab, 2026-11-25 dry run)."""
    onsite = posting("Bangalore", BASE, order=0)
    bridge = posting("H", BASE[:50], source="himalayas", quality="aggregator_full", order=1)
    remote = posting("Remote", BASE, order=2, remote="remote")
    assert groups([onsite, bridge, remote], None) == {"H": "Bangalore", "Remote": "Bangalore"}
    assert groups([onsite, bridge, remote], CANONICAL_MIN) == {"H": "Bangalore"}
