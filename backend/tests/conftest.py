"""Fixtures współdzielone przez testy backendu.

Brak jeszcze osobnej bazy testowej w `docker-compose.yml` (etap 2) — testy
uruchamiane przez `make test`/`make check` działają w kontenerze `api`
i celują w tego samego Postgresa co dev (`DATABASE_URL` z `.env`). Żeby
testy się nie depczyły, `_clean_auth_tables` czyści tabele modułu `auth`
przed każdym testem.

`override_get_db` jest tu jawnie zdefiniowany (mimo że dziś wskazuje na tę
samą sesję co produkcyjny `get_db`), żeby moduł mógł w przyszłości podmienić
połączenie na dedykowaną bazę testową bez zmiany testów.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import get_redis
from app.core.rate_limit import limiter
from app.db.session import AsyncSessionLocal, engine, get_db
from app.main import app


async def _override_get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session


app.dependency_overrides[get_db] = _override_get_db


@pytest_asyncio.fixture(autouse=True)
async def _clean_auth_tables() -> AsyncGenerator[None, None]:
    """Czyści `users`/`refresh_tokens` przed każdym testem (izolacja testów)."""
    async with engine.begin() as conn:
        await conn.execute(text("TRUNCATE TABLE refresh_tokens, users CASCADE"))
    yield


@pytest_asyncio.fixture(autouse=True)
async def _reset_rate_limiter() -> None:
    """Czyści liczniki OBU limiterów w Redisie przed każdym testem.

    Bez tego limity (np. `AUTH_RATE_LIMIT` na `/auth/register`/`/auth/login`)
    liczyłyby się kumulatywnie po całej sesji pytest — wszystkie żądania
    testowe trafiają z tego samego "adresu" (`ASGITransport` nie ustawia
    `request.client`, `get_remote_address` zwraca stały fallback), więc bez
    resetu porządek i liczba testów w innych plikach wpływałaby na to, czy
    dany test przypadkiem nie łapie 429. Ta sama zasada izolacji co
    `_clean_auth_tables` powyżej, tylko dla magazynu Redis limitera
    zamiast tabel Postgresa.

    Dwa mechanizmy = dwa magazyny do wyczyszczenia (patrz `core/rate_limit.py`):
    `limiter.reset()` zdejmuje liczniki slowapi (dekoratory `/auth/*`), a
    `DELETE ratelimit:default:*` — liczniki limitu domyślnego. Po dodaniu
    tego drugiego limitu bez czyszczenia suita zaczęłaby się sypać dopiero
    przy ~100 żądaniach w minucie, czyli losowo i zależnie od kolejności.
    """
    limiter.reset()
    redis = get_redis()
    keys = [key async for key in redis.scan_iter(match="ratelimit:default:*")]
    if keys:
        await redis.delete(*keys)


@pytest_asyncio.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """Sesja do bezpośrednich asercji/setupu w testach (poza żądaniami HTTP)."""
    async with AsyncSessionLocal() as session:
        yield session


@pytest_asyncio.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    """Async klient HTTP działający w procesie testowym na ASGI aplikacji."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
