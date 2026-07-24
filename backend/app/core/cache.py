"""Klient Redis — czysty cache, nigdy źródło prawdy (CLAUDE.md #3.7).

Redis można w każdej chwili wyczyścić i aplikacja musi działać dalej
(wolniej, nie: błąd). Logika kluczy wersjonowanych
`{zasob}:{portfolio_id}:{ostatnia_edycja_holdings}:{data_eod}` i TTL
powstaje wraz z modułem `analytics` (etap 6, plan krok 31) — tu tylko
szkielet połączenia.
"""

from __future__ import annotations

from functools import lru_cache

from redis.asyncio import Redis

from app.core.config import get_settings


@lru_cache
def get_redis() -> Redis:
    """Zwraca (leniwie tworzony) klient Redis skonfigurowany z `REDIS_URL`."""
    settings = get_settings()
    return Redis.from_url(settings.redis_url, decode_responses=True)
