"""Klient Redis — czysty cache, nigdy źródło prawdy (CLAUDE.md #3.7).

Redis można w każdej chwili wyczyścić i aplikacja musi działać dalej
(wolniej, nie: błąd) — `get_cached_json`/`set_cached_json` poniżej łapią
**wyłącznie** `redis.exceptions.RedisError` (błędy połączenia/protokołu:
`ConnectionError`, `TimeoutError`, serwer nieosiągalny) i degradują do
`None`/no-op zamiast propagować wyjątek do wołającego (`modules/analytics/
service.py`) — patrz test `tests/integration/test_analytics.py::
test_allocation_survives_redis_outage` (krok 31). Błędy programistyczne
(np. zły typ argumentu) **nie** są tu łapane — to nie jest ogólny
`except Exception`, bo to ukryłoby prawdziwe bugi, nie tylko awarię
infrastruktury.

Format klucza wersjonowanego (`cache_key`) i logika `eod_marker` (segment
„data EOD") powstają w module `analytics` (etap 6, plan krok 31) — tu tylko
połączenie i budowa/odczyt/zapis samego klucza, generyczne dla każdego
zasobu (`resource`), nie tylko `analytics`.
"""

from __future__ import annotations

from functools import lru_cache
from typing import cast
from uuid import UUID

import structlog
from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.core.config import get_settings

logger = structlog.get_logger(__name__)


@lru_cache
def get_redis() -> Redis:
    """Zwraca (leniwie tworzony) klient Redis skonfigurowany z `REDIS_URL`."""
    settings = get_settings()
    return Redis.from_url(settings.redis_url, decode_responses=True)


def cache_key(
    resource: str,
    portfolio_id: UUID,
    holdings_version: int,
    eod_marker: str,
    *extra: str,
) -> str:
    """Klucz cache wersjonowany (CLAUDE.md #3.7):
    `{resource}:{portfolio_id}:[extra:...:]{holdings_version}:{eod_marker}`.

    `extra` to dodatkowe segmenty **między** `portfolio_id` a
    `holdings_version` — np. wymiar alokacji (`by=class|sector|...`), bo
    `GET /allocation` cache'uje osobno per wymiar (ten sam wynik dla
    `by=class` i `by=sector` byłby błędny). Bez `extra` (koncentracja,
    ranking rynków — jeden wynik na portfel) klucz odpowiada dosłownie
    formatowi z CLAUDE.md #3.7.

    Nie ma tu inwalidacji — zmiana `holdings_version` (mutacja `holdings`)
    albo `eod_marker` (nowe dane EOD) **zmienia klucz**, stary wpis w
    Redisie po prostu wygasa przez TTL (skill `fastapi-modul`: „Dzięki
    temu nie ma inwalidacji — zmiana składu zmienia klucz").
    """
    parts = [resource, str(portfolio_id), *extra, str(holdings_version), eod_marker]
    return ":".join(parts)


async def get_cached_json(key: str) -> str | None:
    """Odczyt cache — `None` zarówno na „brak wpisu", jak i na „Redis
    niedostępny" (wołający nie rozróżnia tych dwóch przypadków, w obu
    liczy na nowo, CLAUDE.md #3.7)."""
    try:
        redis = get_redis()
        value = await redis.get(key)
        # Klient skonfigurowany z `decode_responses=True` (`get_redis` wyżej)
        # zawsze zwraca `str | None` w praktyce — `cast` tylko dla typów,
        # stub `redis-py` deklaruje szerszy `ResponseT`.
        return cast("str | None", value)
    except RedisError:
        logger.warning("cache.get_failed", key=key)
        return None


async def set_cached_json(key: str, value: str, *, ttl_seconds: int) -> None:
    """Zapis cache z TTL — best-effort, nigdy nie podnosi wyjątku dalej
    (awaria zapisu do Redisa nie może wywalić odpowiedzi, która już
    policzyła poprawny wynik, CLAUDE.md #3.7)."""
    try:
        redis = get_redis()
        await redis.set(key, value, ex=ttl_seconds)
    except RedisError:
        logger.warning("cache.set_failed", key=key)
