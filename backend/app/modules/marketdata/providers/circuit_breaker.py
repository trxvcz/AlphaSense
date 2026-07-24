"""`CircuitBreaker` per dostawca danych rynkowych, stan w Redisie.

Po `failure_threshold` błędach pod rząd obwód się otwiera na
`reset_timeout` sekund — w tym czasie `Guarded` (`guarded.py`) w ogóle nie
odpytuje dostawcy (`is_open() == True`), żeby nie dobijać już
niedziałającego/wolnego API i nie czekać na jego timeouty przy każdym
żądaniu. Po upływie `reset_timeout` dokładnie jedno zapytanie dostaje
szansę (`allow_trial()`, stan half-open): sukces zamyka obwód, porażka
restartuje zegar na kolejne `reset_timeout` sekund.

Stan trzymany w Redisie (nie w pamięci procesu), żeby przetrwał restart
workera i był współdzielony między procesami/replikami sięgającymi po
tego samego dostawcę (ten sam powód co `RateLimiter`, patrz jego
docstring). Zdarzenia otwarcia/zamknięcia obwodu logowane przez
`structlog` — to ważne info operacyjne (SKILL `data-provider`), inaczej
nikt się nie dowie, że dostawca przestał odpowiadać, dopóki nie zauważy
nieświeżych danych.
"""

from __future__ import annotations

from typing import Final

import structlog
from redis.asyncio import Redis

from app.core.cache import get_redis
from app.core.config import get_settings
from app.modules.marketdata.providers.clock import ClockFn, default_clock

logger = structlog.get_logger(__name__)

_STATE_OPEN: Final[str] = "open"

# TTL na `_state_key`, odświeżane przy każdym zapisie. Znacznie dłuższe niż
# jakikolwiek realny odstęp między wywołaniami tego samego dostawcy (joby
# EOD odpytują raz dziennie), więc nie zaburza normalnego liczenia błędów —
# ale zapobiega temu, żeby stan po dostawcy, którego nikt już nigdy nie
# odpyta (np. usunięty z `asset_source_map`), został w Redisie na zawsze.
_STATE_TTL_SECONDS: Final[int] = 30 * 24 * 3600


class CircuitBreaker:
    """Obwód per dostawca (`provider` = nazwa).

    Domyślne `failure_threshold`/`reset_timeout` pochodzą z konfiguracji
    (`Settings.circuit_failure_threshold`/`circuit_reset_seconds`,
    `.env.example`) — nadpisywalne per instancja, bo różni dostawcy mogą
    chcieć różnej tolerancji (np. NBP, jedyne źródło FX, może dostać
    dłuższy `reset_timeout` niż fallback dla zagranicznych akcji).
    """

    def __init__(
        self,
        provider: str,
        *,
        failure_threshold: int | None = None,
        reset_timeout: int | None = None,
        redis: Redis | None = None,
        clock: ClockFn = default_clock,
    ) -> None:
        settings = get_settings()
        self.provider = provider
        self.failure_threshold = (
            failure_threshold
            if failure_threshold is not None
            else settings.circuit_failure_threshold
        )
        self.reset_timeout = (
            reset_timeout if reset_timeout is not None else settings.circuit_reset_seconds
        )
        if self.failure_threshold < 1:
            raise ValueError("failure_threshold musi być co najmniej 1")
        if self.reset_timeout < 1:
            raise ValueError("reset_timeout musi być co najmniej 1 (sekunda)")
        self._redis = redis if redis is not None else get_redis()
        self._clock = clock
        self._state_key = f"circuit_breaker:{provider}:state"
        self._trial_key = f"circuit_breaker:{provider}:trial"

    async def is_open(self) -> bool:
        """Czy obwód jest aktualnie otwarty (niezależnie od tego, czy
        upłynął już `reset_timeout` — to sprawdza `allow_trial()`)."""
        state = await self._redis.hget(self._state_key, "state")
        return state == _STATE_OPEN

    async def allow_trial(self) -> bool:
        """Czy wolno przepuścić jedno próbne zapytanie (half-open).

        Zwraca `True` co najwyżej raz na `reset_timeout` — kolejni wołający
        w tym samym oknie (np. inny worker) dostają `False`, dopóki próbne
        zapytanie nie zostanie rozstrzygnięte (`record_success`/
        `record_failure`) albo `_trial_key` nie wygaśnie (TTL = `reset_timeout`,
        zabezpieczenie przed trwałym zablokowaniem obwodu, gdyby wołający
        ubił proces w trakcie próbnego zapytania).
        """
        opened_at_raw = await self._redis.hget(self._state_key, "opened_at")
        if opened_at_raw is None:
            return False
        opened_at = float(opened_at_raw)
        if self._clock() - opened_at < self.reset_timeout:
            return False
        claimed = await self._redis.set(self._trial_key, "1", nx=True, ex=self.reset_timeout)
        return bool(claimed)

    async def record_success(self) -> None:
        """Zamyka obwód (jeśli był otwarty) i zeruje licznik błędów."""
        previous_state = await self._redis.hget(self._state_key, "state")
        await self._redis.delete(self._state_key, self._trial_key)
        if previous_state == _STATE_OPEN:
            logger.info("circuit_breaker.closed", provider=self.provider)

    async def record_failure(self) -> None:
        """Odnotowuje błąd; po `failure_threshold` błędach pod rząd otwiera
        obwód. Błąd zgłoszony, gdy obwód jest już otwarty, oznacza porażkę
        próbnego zapytania (half-open) — restartuje zegar, nie liczy się do
        `failure_threshold` od nowa (obwód i tak jest już otwarty)."""
        previous_state = await self._redis.hget(self._state_key, "state")
        if previous_state == _STATE_OPEN:
            await self._redis.hset(self._state_key, "opened_at", self._clock())
            await self._redis.expire(self._state_key, _STATE_TTL_SECONDS)
            await self._redis.delete(self._trial_key)
            logger.warning(
                "circuit_breaker.trial_failed",
                provider=self.provider,
                reset_timeout=self.reset_timeout,
            )
            return

        failures = await self._redis.hincrby(self._state_key, "failures", 1)
        await self._redis.expire(self._state_key, _STATE_TTL_SECONDS)
        if failures >= self.failure_threshold:
            await self._redis.hset(
                self._state_key,
                mapping={"state": _STATE_OPEN, "opened_at": self._clock()},
            )
            await self._redis.expire(self._state_key, _STATE_TTL_SECONDS)
            logger.warning(
                "circuit_breaker.opened",
                provider=self.provider,
                failures=failures,
                reset_timeout=self.reset_timeout,
            )
