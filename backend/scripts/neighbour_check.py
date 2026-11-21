"""Before/after sanity check for an embedding change. Not a tuned evaluation.

python -m scripts.neighbour_check snapshot [--seed 7] [--sample 10]
    Copies every current embedding into scratch.embedding_before and picks a random
    sample of active, non-duplicate jobs (stored in scratch.neighbour_sample).
    Run it BEFORE re-embedding. Refuses to overwrite an existing snapshot.
python -m scripts.neighbour_check compare [--k 5]
    For each sampled job, its k nearest active, non-duplicate neighbours by cosine
    using the snapshot vectors (before) and the current vectors (after). Exact search
    (no index), over jobs present in both, so the two lists are comparable.
python -m scripts.neighbour_check drop
    Removes the scratch schema.
"""

import argparse
import random
import sys
from typing import Any

from sqlalchemy import Connection, create_engine, text

from app.core.config import get_settings

_CANDIDATES = """
    j.status != 'expired' AND j.duplicate_of IS NULL AND j.embedding IS NOT NULL
    AND j.id IN (SELECT id FROM scratch.embedding_before)
"""


def snapshot(conn: Connection, seed: int, size: int) -> None:
    exists = conn.scalar(text("SELECT to_regclass('scratch.embedding_before') IS NOT NULL"))
    if exists:
        sys.exit("scratch.embedding_before already exists; run `drop` first to replace it")
    conn.execute(text("CREATE SCHEMA IF NOT EXISTS scratch"))
    conn.execute(
        text("""
        CREATE TABLE scratch.embedding_before AS
        SELECT id, embedding, embedded_hash FROM jobs
        WHERE status != 'expired' AND embedding IS NOT NULL
        """)
    )
    conn.execute(text("ALTER TABLE scratch.embedding_before ADD PRIMARY KEY (id)"))
    ids = conn.scalars(
        text(f"SELECT j.id FROM jobs j WHERE {_CANDIDATES} ORDER BY j.id")  # noqa: S608
    ).all()
    sample = random.Random(seed).sample(list(ids), size)  # noqa: S311 -- reproducible sample
    conn.execute(text("CREATE TABLE scratch.neighbour_sample (pos int, id uuid)"))
    conn.execute(
        text("INSERT INTO scratch.neighbour_sample VALUES (:pos, :id)"),
        [{"pos": i, "id": job_id} for i, job_id in enumerate(sample)],
    )
    copied = conn.scalar(text("SELECT count(*) FROM scratch.embedding_before"))
    print(f"snapshot: {copied} embeddings; sample of {size} from {len(ids)} (seed {seed})")


def _neighbours(conn: Connection, job_id: Any, table: str, k: int) -> list[Any]:
    vector = "b.embedding" if table == "before" else "j.embedding"
    join = "JOIN scratch.embedding_before b ON b.id = j.id" if table == "before" else ""
    query_vector = (
        "(SELECT embedding FROM scratch.embedding_before WHERE id = :id)"
        if table == "before"
        else "(SELECT embedding FROM jobs WHERE id = :id)"
    )
    sql = f"""
        SELECT j.title, c.name AS company, 1 - ({vector} <=> {query_vector}) AS cosine
        FROM jobs j {join} JOIN companies c ON c.id = j.company_id
        WHERE {_CANDIDATES} AND j.id != :id
        ORDER BY {vector} <=> {query_vector}
        LIMIT :k
    """  # noqa: S608 -- only fixed fragments are interpolated
    return list(conn.execute(text(sql), {"id": job_id, "k": k}).all())


def compare(conn: Connection, k: int) -> None:
    conn.execute(text("SET enable_indexscan = off"))  # exact search, never the HNSW index
    sample = conn.execute(
        text("""
        SELECT s.pos, j.id, j.title, c.name AS company
        FROM scratch.neighbour_sample s JOIN jobs j ON j.id = s.id
        JOIN companies c ON c.id = j.company_id ORDER BY s.pos
        """)
    ).all()
    same_company = {"before": 0, "after": 0}
    total = 0
    for row in sample:
        print(f"\n### {row.pos + 1}. {row.title} ({row.company})\n")
        print("| # | Before | After |\n|---|---|---|")
        before = _neighbours(conn, row.id, "before", k)
        after = _neighbours(conn, row.id, "after", k)
        for i in range(k):
            cells = []
            for label, found in (("before", before), ("after", after)):
                if i < len(found):
                    n = found[i]
                    same_company[label] += n.company == row.company
                    cells.append(f"{n.title} ({n.company}) {n.cosine:.3f}")
                else:
                    cells.append("")
            total += 1
            print(f"| {i + 1} | {cells[0]} | {cells[1]} |")
    print(
        f"\nNeighbours at the same company as the query job: "
        f"before {same_company['before']}/{total}, after {same_company['after']}/{total}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m scripts.neighbour_check")
    sub = parser.add_subparsers(dest="command", required=True)
    snap = sub.add_parser("snapshot")
    snap.add_argument("--seed", type=int, default=7)
    snap.add_argument("--sample", type=int, default=10)
    cmp_ = sub.add_parser("compare")
    cmp_.add_argument("--k", type=int, default=5)
    sub.add_parser("drop")
    args = parser.parse_args()

    engine = create_engine(get_settings().database_url)
    with engine.begin() as conn:
        if args.command == "snapshot":
            snapshot(conn, args.seed, args.sample)
        elif args.command == "compare":
            compare(conn, args.k)
        else:
            conn.execute(text("DROP SCHEMA IF EXISTS scratch CASCADE"))
            print("dropped scratch schema")
    engine.dispose()


if __name__ == "__main__":
    main()
