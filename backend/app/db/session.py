"""Silnik bazy danych i sesje async SQLAlchemy.

Connection string wyłącznie z `app.core.config.Settings.database_url`
(pydantic-settings) — zero hardkodowanych URL-i, zgodnie z docs/konwencje.md.
`get_db` jest zależnością FastAPI (`Depends(get_db)`), która otwiera sesję
na czas obsługi żądania i zawsze ją zamyka (async generator + `yield`).
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import get_settings

settings = get_settings()

engine: AsyncEngine = create_async_engine(settings.database_url, pool_pre_ping=True)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    autoflush=False,
    expire_on_commit=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Zależność FastAPI: otwiera sesję na czas żądania i zamyka po odpowiedzi."""
    async with AsyncSessionLocal() as session:
        yield session


DbSession = Annotated[AsyncSession, Depends(get_db)]
