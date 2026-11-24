"""Filtered vector search over the HNSW index.

The WHERE clause is the same `allowed(rules)` expression the filter stage and the
ruled-out labels use. HNSW applies a WHERE after the index scan, so with a selective
filter a plain scan can stop with fewer than k rows. pgvector 0.8's iterative scan keeps
scanning until k rows pass the filter (or `hnsw.max_scan_tuples` is reached).
`relaxed_order` may return rows slightly out of distance order, so the rows are re-sorted
here. EXPLAIN ANALYZE for the filtered and unfiltered query is in docs/retrieval.md.
"""

import uuid

from sqlalchemy import ColumnElement, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Company, Job


async def vector_search(
    session: AsyncSession,
    query_vector: list[float],
    where: ColumnElement[bool],
    *,
    k: int,
    ef_search: int,
    join_company: bool = False,
) -> list[tuple[uuid.UUID, float]]:
    """Top-k (job id, cosine distance), nearest first, among jobs matching `where`."""
    # SET LOCAL lasts until the end of the current transaction only. Values are ints and
    # a fixed keyword, never user input; SET cannot take bind parameters.
    await session.execute(text(f"SET LOCAL hnsw.ef_search = {int(ef_search)}"))
    await session.execute(text("SET LOCAL hnsw.iterative_scan = relaxed_order"))
    distance = Job.embedding.cosine_distance(query_vector).label("distance")
    statement = select(Job.id, distance)
    if join_company:
        statement = statement.join(Company, Company.id == Job.company_id)
    statement = statement.where(where, Job.embedding.is_not(None)).order_by(distance).limit(k)
    rows = (await session.execute(statement)).all()
    return sorted(((row.id, float(row.distance)) for row in rows), key=lambda r: r[1])
