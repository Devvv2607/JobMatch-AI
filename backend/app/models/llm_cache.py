from sqlalchemy import Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAt


class LLMCacheEntry(Base, CreatedAt):
    """Cached LLM response, keyed on hash(prompt name, prompt version, model, input).

    Shared across users by design: identical input gives identical output at
    temperature 0. Rows hold model output only, never the input text.
    """

    __tablename__ = "llm_cache"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    provider: Mapped[str] = mapped_column(String(32))
    model: Mapped[str] = mapped_column(String(128))
    prompt_name: Mapped[str] = mapped_column(String(64), index=True)
    prompt_version: Mapped[int] = mapped_column(Integer)
    response: Mapped[str] = mapped_column(Text)
    prompt_tokens: Mapped[int] = mapped_column(Integer)
    completion_tokens: Mapped[int] = mapped_column(Integer)
