"""Chained near-duplicate groups (app/ingest/dedup.py, assign_groups): a posting joins a
group only if it also matches the group's canonical posting at INGEST_NEAR_DUPLICATE_
CANONICAL_MIN (0.85). Owner review 2026-11-25: an AlphaSense chain through a Himalayas
posting merged two different roles (Jaccard 0.447 with the kept job), while MongoDB city
variants chained at 0.88-0.89 against the kept job are the same role.

Also: same source + same normalised location needs Jaccard >= 0.97 (Stripe, Dublin, two
requisitions at 0.935), and owner "different" verdicts (data/not_duplicates.yaml) are
never grouped."""

import uuid
from datetime import UTC, datetime, timedelta
from itertools import combinations

from app.ingest.dedup import (
    Posting,
    TextRules,
    assign_groups,
    jaccard,
    match,
    not_duplicates,
)

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
    location: str | None = None,
) -> Posting:
    return Posting(
        id=uuid.uuid5(uuid.NAMESPACE_DNS, name),
        source=source,
        quality=quality,
        first_seen=T0 + timedelta(hours=order),
        posted_at=None,
        location=location or name,
        location_norm=(location or name).lower().replace(",", ""),
        eligibility=("listed", ("IN",)),
        remote_policy=remote,
        words=frozenset(word_list),
        source_id=name,
    )


def groups(
    members: list[Posting],
    canonical_min: float | None,
    *,
    same_location_min: float | None = None,
    apart: frozenset[frozenset[str]] = frozenset(),
) -> dict[str, str]:
    """Hidden posting -> the posting it is hidden under, by name (source_id). Edges are
    built as find_text_duplicates builds them."""
    rules = TextRules(THRESHOLD, canonical_min, same_location_min, apart)
    edges = [
        (a, b)
        for a, b in combinations(members, 2)
        if match(a, b, THRESHOLD, same_location_min) and frozenset((a.key, b.key)) not in apart
    ]
    return {d.source_id: c.source_id for d, c in assign_groups(edges, rules).items()}


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


def test_same_source_same_location_needs_097() -> None:
    """Stripe, 2026-11-25: "Dublin, Ireland" and "Dublin", Jaccard 0.935, two requisitions."""
    kept = posting("6717520", BASE, order=0, location="Dublin, Ireland")
    other = posting("8261012", [*BASE[:93], "x1", "x2"], order=1, location="Dublin")
    assert 0.90 <= jaccard(kept.words, other.words) < 0.97
    assert groups([kept, other], CANONICAL_MIN) == {"8261012": "6717520"}  # before
    assert groups([kept, other], CANONICAL_MIN, same_location_min=0.97) == {}


def test_same_location_at_097_or_more_still_merges() -> None:
    a = posting("A", BASE, order=0, location="Pune")
    b = posting("B", BASE[:98], order=1, location="Pune")  # Jaccard 0.98: a repost
    assert groups([a, b], CANONICAL_MIN, same_location_min=0.97) == {"B": "A"}


def test_different_locations_keep_the_090_rule() -> None:
    a = posting("A", BASE, order=0, location="Baddi")
    b = posting("B", BASE[:93], order=1, location="Sikar")  # Jaccard 0.93: city variant
    assert groups([a, b], CANONICAL_MIN, same_location_min=0.97) == {"B": "A"}


def test_same_location_rule_applies_to_the_canonical_check_too() -> None:
    """A same-city posting cannot ride a chain through another city into the group."""
    a = posting("A", BASE, order=0, location="Dublin")
    b = posting("B", BASE[:95], order=1, location="London")  # 0.95 with A
    c = posting("C", BASE[:93], order=2, location="Dublin")  # 0.93 with A, 0.98 with B
    assert groups([a, b, c], CANONICAL_MIN, same_location_min=0.97) == {"B": "A"}


def test_pairs_the_owner_keeps_apart_never_share_a_group() -> None:
    a = posting("A", BASE, order=0)
    b = posting("B", BASE[:97], order=1)
    c = posting("C", BASE[:95], order=2)
    apart = frozenset({frozenset(("greenhouse:A", "greenhouse:C"))})
    assert groups([a, b, c], CANONICAL_MIN) == {"B": "A", "C": "A"}
    assert groups([a, b, c], CANONICAL_MIN, apart=apart) == {"B": "A"}
    # Kept apart from a member, not the canonical: still leaves.
    apart_bc = frozenset({frozenset(("greenhouse:B", "greenhouse:C"))})
    assert groups([a, b, c], CANONICAL_MIN, apart=apart_bc) == {"B": "A"}


def test_owner_verdicts_file_lists_the_stripe_and_alphasense_pairs() -> None:
    pairs = not_duplicates()
    assert frozenset(("greenhouse:6717520", "greenhouse:8261012")) in pairs
    assert frozenset(("greenhouse:8025882002", "greenhouse:8355650002")) in pairs
