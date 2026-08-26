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
from app.db.rls import register_rls_listener

settings = get_settings()

# Silnik aplikacji. W API wskazuje na rolę `portfel_app` (podlegającą RLS),
# w workerze i CLI `DATABASE_URL_APP` jest pusty, więc schodzi do roli
# właściciela — to jest miejsce, w którym „worker z rolą BYPASSRLS" z
# ADR-002 staje się faktem, bez rozdwajania kodu dostępu do bazy.
engine: AsyncEngine = create_async_engine(
    settings.database_url_app or settings.database_url, pool_pre_ping=True
)

# ADR-002 warstwa 3 (krok 44): każda transakcja tego silnika dostaje
# `SET LOCAL app.user_id` z kontekstu żądania. Rejestracja tutaj, a nie
# w `main.py`, bo silnik jest jeden i ma być niemożliwe otwarcie sesji,
# która ominęła listener — także w workerze i w testach. Dla roli
# właściciela ustawienie jest po prostu bez skutku (polityki jej nie
# dotyczą), więc listener nie potrzebuje gałęzi „to nie API".
register_rls_listener(engine.sync_engine)

# Silnik WŁAŚCICIELA — do zadań, które z definicji stoją poza kontekstem
# jednego użytkownika: migracje, czyszczenie tabel w testach, operacje
# administracyjne CLI. Trzymany osobno i **nieużywany przez żadną trasę**,
# żeby „potrzebuję obejść RLS" wymagało jawnego importu, a nie flagi.
owner_engine: AsyncEngine = create_async_engine(settings.database_url, pool_pre_ping=True)

# Sesja właściciela. **Tego używają joby workera i CLI** — z definicji
# działają na danych wszystkich użytkowników i nie mają czyjegoś
# `app.user_id` (job wyceny liczy snapshoty całej bazy). Gdyby brały
# `AsyncSessionLocal`, ich poprawność zależałaby od tego, czy dany kontener
# dostał `DATABASE_URL_APP` — a to zbyt cicha zależność jak na job, którego
# awaria objawia się „portfeli: 0" w logu zamiast błędem.
OwnerSessionLocal = async_sessionmaker(bind=owner_engine, autoflush=False, expire_on_commit=False)

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
