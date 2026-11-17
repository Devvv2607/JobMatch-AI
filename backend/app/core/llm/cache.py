from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.llm.types import LLMResult
from app.models import LLMCacheEntry


class PostgresLLMCache:
    """Uses its own short transactions so a cache write never joins a request's."""

    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        self._sessionmaker = sessionmaker

    async def get(self, key: str) -> LLMResult | None:
        async with self._sessionmaker() as session:
            row = await session.scalar(select(LLMCacheEntry).where(LLMCacheEntry.key == key))
        if row is None:
            return None
        return LLMResult(
            text=row.response,
            provider=row.provider,
            model=row.model,
            prompt_tokens=row.prompt_tokens,
            completion_tokens=row.completion_tokens,
            cached=True,
        )

    async def put(
        self, key: str, result: LLMResult, *, prompt_name: str, prompt_version: int
    ) -> None:
        statement = (
            insert(LLMCacheEntry)
            .values(
                key=key,
                provider=result.provider,
                model=result.model,
                prompt_name=prompt_name,
                prompt_version=prompt_version,
                response=result.text,
                prompt_tokens=result.prompt_tokens,
                completion_tokens=result.completion_tokens,
            )
            .on_conflict_do_nothing(index_elements=[LLMCacheEntry.key])
        )
        async with self._sessionmaker() as session:
            await session.execute(statement)
            await session.commit()
