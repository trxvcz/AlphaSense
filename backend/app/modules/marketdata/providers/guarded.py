"""`Guarded` — dekorator nad `DataProvider`, spina `RateLimiter` i
`CircuitBreaker` wokół każdego wywołania (plan krok 20, etap 4).

`Guarded` sam implementuje `DataProvider` (proxy) — kod ingestii (przyszłe
kroki) wywołuje `Guarded` dokładnie tak samo jak nieowinięty provider, nie
musi wiedzieć o istnieniu limitera/obwodu. `FallbackChain` (`fallback_chain.py`)
składa listę instancji `Guarded`, nie surowych providerów — obwiązanie
limiterem/breakerem następuje raz, przy budowie łańcucha (`service.py`,
przyszły krok), nie w tym module.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import date
from typing import TypeVar

from app.core.errors import ProviderUnavailableError
from app.modules.marketdata.providers.base import (
    AssetMetadata,
    DataProvider,
    FxQuote,
    PriceBar,
)
from app.modules.marketdata.providers.circuit_breaker import CircuitBreaker
from app.modules.marketdata.providers.rate_limiter import RateLimiter

_T = TypeVar("_T")


class Guarded:
    """Owija `provider` limiterem (`limiter`) i obwodem (`breaker`).

    Kolejność sprawdzeń w `_guarded_call`, w tej konkretnej kolejności z
    powodu:
    1. `breaker.is_open()` — jeśli dostawca i tak nie działa, nie ma sensu
       czekać na token limitera ani na timeout sieciowy samego wywołania.
    2. `limiter.acquire()` — czeka na dostępny token *dopiero* jeśli obwód
       pozwala na wywołanie (zamknięty albo próbne).
    3. samo wywołanie `provider.<metoda>` — wynik aktualizuje obwód
       (`record_success`/`record_failure`); jeśli providerowi zabraknie
       tokenów u niego samego i odpowie HTTP 429, to obsługa (`limiter.
       backoff`) jest zadaniem konkretnego providera (SKILL `data-provider`),
       nie tego wrappera — stąd `Guarded` łapie tu każdy wyjątek, jaki
       provider rzuci (429 przerobione na wyjątek przez providera również),
       zaokrąglając go w `record_failure`.
    """

    def __init__(
        self, provider: DataProvider, limiter: RateLimiter, breaker: CircuitBreaker
    ) -> None:
        self._provider = provider
        self._limiter = limiter
        self._breaker = breaker
        self.name = provider.name
        self.supports = provider.supports

    async def _guarded_call(self, call: Callable[[], Awaitable[_T]]) -> _T:
        if await self._breaker.is_open() and not await self._breaker.allow_trial():
            raise ProviderUnavailableError(
                f"Dostawca {self.name} niedostępny (obwód otwarty)",
                details={"provider": self.name},
            )
        await self._limiter.acquire()
        try:
            result = await call()
        except Exception:
            await self._breaker.record_failure()
            raise
        else:
            await self._breaker.record_success()
            return result

    async def get_ohlcv(self, symbol: str, start: date, end: date) -> list[PriceBar]:
        return await self._guarded_call(lambda: self._provider.get_ohlcv(symbol, start, end))

    async def get_fx(self, currency: str, start: date, end: date) -> list[FxQuote]:
        return await self._guarded_call(lambda: self._provider.get_fx(currency, start, end))

    async def get_metadata(self, symbol: str) -> AssetMetadata | None:
        return await self._guarded_call(lambda: self._provider.get_metadata(symbol))
