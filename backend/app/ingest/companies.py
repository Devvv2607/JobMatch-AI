"""companies.yaml: the boards we ingest, with industry tags."""

from dataclasses import dataclass
from pathlib import Path

import yaml
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.ingest.text import normalise_key
from app.models import Company

COMPANIES_FILE = Path(__file__).parent / "data" / "companies.yaml"
ATS_SOURCES = ("greenhouse", "lever", "ashby")


@dataclass(frozen=True)
class CompanyEntry:
    name: str
    ats: str
    token: str
    industries: tuple[str, ...]


def load_companies(path: Path = COMPANIES_FILE) -> list[CompanyEntry]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    entries = [
        CompanyEntry(
            name=str(item["name"]),
            ats=str(item["ats"]),
            token=str(item["token"]),
            industries=tuple(str(tag) for tag in item["industries"]),
        )
        for item in raw["companies"]
    ]
    for entry in entries:
        if entry.ats not in ATS_SOURCES:
            raise ValueError(f"{entry.name}: unknown ats {entry.ats!r}")
        if not entry.industries:
            raise ValueError(f"{entry.name}: industries must not be empty")
    slugs = [company_slug(e.name) for e in entries]
    if len(set(slugs)) != len(slugs):
        raise ValueError("companies.yaml has duplicate company names")
    return entries


def company_slug(name: str) -> str:
    """Join key across sources: "Postman, Inc." and "postman" are the same company."""
    key = normalise_key(name)
    for suffix in (
        " inc",
        " llc",
        " ltd",
        " limited",
        " gmbh",
        " corp",
        " corporation",
        " co",
        " pvt",
        " private",
        " technologies",
        " labs",
        " ai",
        " hq",
    ):
        if key.endswith(suffix) and len(key) > len(suffix) + 2:
            key = key[: -len(suffix)]
    return key.replace(" ", "-")[:128]


async def sync_companies(session: AsyncSession, entries: list[CompanyEntry]) -> dict[str, Company]:
    """Upserts the configured companies; returns them keyed by board token."""
    for entry in entries:
        statement = insert(Company).values(
            slug=company_slug(entry.name),
            name=entry.name,
            ats=entry.ats,
            board_token=entry.token,
            industries=list(entry.industries),
        )
        await session.execute(
            statement.on_conflict_do_update(
                index_elements=[Company.slug],
                set_={
                    "name": statement.excluded.name,
                    "ats": statement.excluded.ats,
                    "board_token": statement.excluded.board_token,
                    "industries": statement.excluded.industries,
                },
            )
        )
    rows = await session.scalars(select(Company).where(Company.board_token.is_not(None)))
    return {row.board_token: row for row in rows if row.board_token}


async def company_for_name(session: AsyncSession, name: str) -> Company:
    """The company a Remotive posting belongs to, created (industry unknown) if new."""
    slug = company_slug(name)
    existing = await session.scalar(select(Company).where(Company.slug == slug))
    if existing is not None:
        return existing
    statement = (
        insert(Company)
        .values(slug=slug, name=name.strip()[:256], industries=[])
        .on_conflict_do_nothing(index_elements=[Company.slug])
    )
    await session.execute(statement)
    company = await session.scalar(select(Company).where(Company.slug == slug))
    assert company is not None  # noqa: S101  # inserted or already present
    return company
