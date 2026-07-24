"""`RateLimiter` — token bucket per dostawca danych rynkowych, w Redisie.

To **inny** mechanizm niż `app.core.rate_limit` (`slowapi`): tamten ogranicza
ruch *przychodzący* do naszego API (klientów frontendu), ten ogranicza ruch
*wychodzący* z naszego workera/API do darmowych API dostawców (Stooq,
yfinance, Finnhub, ...) — nie da się go zbudować na `slowapi` (to middleware
ASGI, nie generyczny klient do wywołań wychodzących), więc jest to osobna,
prostsza implementacja. Stan w Redisie (nie w pamięci procesu) z tego samego
powodu co `slowapi` w `core/rate_limit.py`: musi przetrwać restart workera i
być współdzielony, jeśli kiedyś workerów będzie więcej niż jeden.

Algorytm liczony atomowo w skrypcie Lua wykonywanym po stronie serwera
Redis — jedna operacja sieciowa na próbę, bez wyścigu
read-modify-write między procesami/workerami sięgającymi po ten sam klucz.
"""

from __future__ import annotations

import random
from typing import Final, cast

import structlog
from redis.asyncio import Redis

from app.core.cache import get_redis
from app.core.errors import ProviderUnavailableError
from app.modules.marketdata.providers.clock import ClockFn, SleepFn, default_clock, default_sleep

logger = structlog.get_logger(__name__)

# KEYS[1] = klucz hasha (`tokens`, `ts`); ARGV = [capacity, refill_per_sec, now, requested]
# Zwraca {allowed (0/1), wait_seconds (string, jeśli allowed=0)}.
_TOKEN_BUCKET_SCRIPT: Final[str] = """
local key = KEYS[1]
local capacity = tonumber(ARGV[1])
local refill_per_sec = tonumber(ARGV[2])
local now = tonumber(ARGV[3])
local requested = tonumber(ARGV[4])

local data = redis.call('HMGET', key, 'tokens', 'ts')
local tokens = tonumber(data[1])
local ts = tonumber(data[2])
if tokens == nil then
  tokens = capacity
  ts = now
end

local elapsed = now - ts
if elapsed < 0 then
  elapsed = 0
end
tokens = math.min(capacity, tokens + elapsed * refill_per_sec)

local allowed = 0
local wait = 0
if tokens >= requested then
  tokens = tokens - requested
  allowed = 1
else
  wait = (requested - tokens) / refill_per_sec
end

redis.call('HSET', key, 'tokens', tostring(tokens), 'ts', tostring(now))
redis.call('EXPIRE', key, 3600)
return {allowed, tostring(wait)}
"""


class RateLimiter:
    """Token bucket per dostawca (`provider` = nazwa, klucz Redis
    `rate_limiter:{provider}`).

    `acquire()` czeka (asynchronicznie, bez blokowania event loopa), aż
    dostępny będzie token — dopiero wtedy wraca do wołającego. `backoff()`
    to osobny helper do obsługi HTTP 429 przez konkretnego dostawcę
    (parsowanie odpowiedzi 429 to zadanie danego providera, nie tego pliku,
    SKILL `data-provider`) — wykładniczy odstęp z jitterem, do
    `max_retries` prób, potem `ProviderUnavailableError`.
    """

    def __init__(
        self,
        provider: str,
        requests_per_minute: int,
        *,
        max_retries: int = 5,
        base_backoff_seconds: float = 1.0,
        redis: Redis | None = None,
        clock: ClockFn = default_clock,
        sleep: SleepFn = default_sleep,
    ) -> None:
        if requests_per_minute <= 0:
            raise ValueError("requests_per_minute musi być dodatnie")
        if max_retries < 1:
            raise ValueError("max_retries musi być co najmniej 1")
        self.provider = provider
        self.requests_per_minute = requests_per_minute
        self.max_retries = max_retries
        self.base_backoff_seconds = base_backoff_seconds
        self._redis = redis if redis is not None else get_redis()
        self._clock = clock
        self._sleep = sleep
        self._key = f"rate_limiter:{provider}"
        self._script = self._redis.register_script(_TOKEN_BUCKET_SCRIPT)

    async def acquire(self, tokens: int = 1) -> None:
        """Czeka, aż `tokens` (domyślnie 1) będzie dostępnych w kubełku."""
        while True:
            allowed, wait_seconds = await self._try_acquire(tokens)
            if allowed:
                return
            await self._sleep(wait_seconds)

    async def _try_acquire(self, tokens: int) -> tuple[bool, float]:
        refill_per_second = self.requests_per_minute / 60.0
        now = self._clock()
        raw_result = await self._script(
            keys=[self._key],
            args=[self.requests_per_minute, refill_per_second, now, tokens],
        )
        # Skrypt Lua zwraca dwuelementową tablicę [int, string] — redis-py
        # nie ma dla tego typu generycznego stuba (`Any` z natury EVAL/EVALSHA),
        # stąd jawny `cast` zamiast ciche `Any` rozlewające się dalej.
        result = cast(list[bytes | str | int], raw_result)
        allowed_raw, wait_raw = result
        return bool(int(allowed_raw)), float(wait_raw)

    async def backoff(self, attempt: int) -> None:
        """Wykładniczy odstęp z jitterem po HTTP 429 (`attempt` liczone od 0
        przez wołający kod dostawcy). Po `max_retries` próbach rzuca
        `ProviderUnavailableError` zamiast czekać w nieskończoność.
        """
        if attempt >= self.max_retries:
            raise ProviderUnavailableError(
                f"Dostawca {self.provider}: przekroczono limit prób "
                f"({self.max_retries}) po HTTP 429",
                details={"provider": self.provider, "attempts": attempt},
            )
        delay = self.base_backoff_seconds * (2**attempt) + random.uniform(
            0, self.base_backoff_seconds
        )
        logger.warning(
            "provider.rate_limited_backoff",
            provider=self.provider,
            attempt=attempt,
            delay_seconds=round(delay, 3),
        )
        await self._sleep(delay)
