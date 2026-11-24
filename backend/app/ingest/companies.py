"""The boards we ingest: companies.yaml (curated by hand, industry tags required) and
companies_discovered.yaml (written by `python -m app.ingest.discover`, each board verified
live; industries may be unknown). A company in both is taken from companies.yaml."""

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.ingest.text import normalise_key
from app.models import Company

COMPANIES_FILE = Path(__file__).parent / "data" / "companies.yaml"
DISCOVERED_FILE = Path(__file__).parent / "data" / "companies_discovered.yaml"
ATS_SOURCES = ("greenhouse", "lever", "ashby", "smartrecruiters", "workable", "recruitee")


@dataclass(frozen=True)
class CompanyEntry:
    name: str
    ats: str
    token: str
    industries: tuple[str, ...]
    website: str | None = None
    yc_batch: str | None = None
    investors: tuple[str, ...] = field(default_factory=tuple)
    discovered_via: str = "manual"


def _entries(path: Path, discovered: bool) -> list[CompanyEntry]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    entries = [
        CompanyEntry(
            name=str(item["name"]),
            ats=str(item["ats"]),
            token=str(item["token"]),
            industries=tuple(str(tag) for tag in item.get("industries") or []),
            website=item.get("website"),
            yc_batch=item.get("yc_batch"),
            investors=tuple(str(i) for i in item.get("investors") or []),
            discovered_via=str(
                item.get("discovered_via") or ("unknown" if discovered else "manual")
            ),
        )
        for item in raw.get("companies") or []
    ]
    for entry in entries:
        if entry.ats not in ATS_SOURCES:
            raise ValueError(f"{entry.name}: unknown ats {entry.ats!r}")
        if not discovered and not entry.industries:
            raise ValueError(f"{entry.name}: industries must not be empty")
    slugs = [company_slug(e.name) for e in entries]
    if len(set(slugs)) != len(slugs):
        raise ValueError(f"{path.name} has duplicate company names")
    return entries


def load_companies(
    path: Path = COMPANIES_FILE, discovered_path: Path | None = DISCOVERED_FILE
) -> list[CompanyEntry]:
    entries = _entries(path, discovered=False)
    if discovered_path is not None and discovered_path.exists():
        curated = {company_slug(e.name) for e in entries}
        curated_boards = {(e.ats, e.token) for e in entries}
        entries += [
            e
            for e in _entries(discovered_path, discovered=True)
            if company_slug(e.name) not in curated and (e.ats, e.token) not in curated_boards
        ]
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
            website=entry.website,
            yc_batch=entry.yc_batch,
            investors=list(entry.investors),
            discovered_via=entry.discovered_via,
        )
        await session.execute(
            statement.on_conflict_do_update(
                index_elements=[Company.slug],
                set_={
                    "name": statement.excluded.name,
                    "ats": statement.excluded.ats,
                    "board_token": statement.excluded.board_token,
                    "industries": statement.excluded.industries,
                    "website": statement.excluded.website,
                    "yc_batch": statement.excluded.yc_batch,
                    "investors": statement.excluded.investors,
                    "discovered_via": statement.excluded.discovered_via,
                },
            )
        )
    rows = await session.scalars(select(Company).where(Company.board_token.is_not(None)))
    return {row.board_token: row for row in rows if row.board_token}


async def company_for_name(session: AsyncSession, name: str) -> Company:
    """The company a feed posting (Remotive, Himalayas, Adzuna) belongs to, created if new:
    industry unknown, discovered_via "aggregator"."""
    slug = company_slug(name)
    existing = await session.scalar(select(Company).where(Company.slug == slug))
    if existing is not None:
        return existing
    statement = (
        insert(Company)
        .values(slug=slug, name=name.strip()[:256], industries=[], discovered_via="aggregator")
        .on_conflict_do_nothing(index_elements=[Company.slug])
    )
    await session.execute(statement)
    company = await session.scalar(select(Company).where(Company.slug == slug))
    assert company is not None  # noqa: S101  # inserted or already present
    return company


# Words a company's legal or trading name adds around its brand.
_LOOSE_SUFFIXES = re.compile(
    r"(?:\s+(?:inc|llc|ltd|limited|pvt|private|plc|gmbh|corp|corporation|co|company|group|"
    r"holdings|technologies|technology|tech|software|solutions|services|systems|labs|ai|hq|"
    r"global|india|international))+$"
)


def match_key(name: str) -> str:
    """Looser than company_slug, for joining an aggregator's company name to a known one:
    "Razorpay Software Private Limited" and "Razorpay" match. Never stored."""
    key = normalise_key(name)
    stripped = _LOOSE_SUFFIXES.sub("", key)
    return (stripped if len(stripped) >= 3 else key).replace(" ", "")


class CompanyIndex:
    """Known companies by slug and by match key, for one source's postings. A name that
    matches nothing is created with unknown industry."""

    def __init__(self, companies: list[Company]) -> None:
        self.by_slug = {c.slug: c for c in companies}
        self.by_key: dict[str, Company] = {}
        for c in sorted(companies, key=lambda c: (c.board_token is None, c.slug)):
            self.by_key.setdefault(match_key(c.name), c)  # boards first

    @classmethod
    async def load(cls, session: AsyncSession) -> "CompanyIndex":
        return cls(list(await session.scalars(select(Company))))

    async def get(self, session: AsyncSession, name: str) -> Company:
        slug = company_slug(name)
        found = self.by_slug.get(slug) or self.by_key.get(match_key(name))
        if found is not None:
            return found
        company = await company_for_name(session, name)
        self.by_slug[company.slug] = company
        self.by_key.setdefault(match_key(company.name), company)
        return company
