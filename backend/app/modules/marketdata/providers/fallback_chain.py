"""`FallbackChain` — próbuje dostawców po kolei (`asset_source_map.priority`),
pierwszy sukces wygrywa (plan krok 20, etap 4).

**Decyzja o kształcie zwrotki:** każda metoda zwraca `tuple[wynik, provider_name]`
zamiast samego wyniku. Alternatywa („ustaw atrybut na wyniku") odpadła, bo
`list[PriceBar]` (zwykła lista) nie niesie miejsca na dodatkowy atrybut bez
podklasy `list`, a `AssetMetadata`/DTO w `base.py` są celowo „głupe" (bez pola
`source`, patrz `base.py`) — dodawanie tam pola provenance tylko dla potrzeb
łańcucha zanieczyściłoby DTO, które też budują pojedynczy `Guarded`/provider
bez wiedzy o łańcuchu. Krotka jest jednolita dla wszystkich trzech metod i
jawna w typach. Wołający (warstwa ingestii, przyszłe kroki) zapisuje
`provider_name` w `ingestion_runs.provider` (CLAUDE.md #4, zasada 3).

`FallbackChain` **nie** implementuje protokołu `DataProvider` — sygnatury
zwrotów są inne (krotka, nie goły wynik), więc to celowo osobny, węższy
interfejs używany przez warstwę ingestii, nie coś podstawialne w miejscu
pojedynczego providera.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import date
from typing import TypeVar

import structlog

from app.core.errors import ProviderUnavailableError
from app.modules.marketdata.providers.base import AssetMetadata, Capability, FxQuote, PriceBar
from app.modules.marketdata.providers.guarded import Guarded

logger = structlog.get_logger(__name__)

_T = TypeVar("_T")


class FallbackChain:
    """Lista `Guarded` providerów w kolejności priorytetu (najwyższy
    priorytet — czyli najpierw próbowany — pierwszy w liście; kolejność
    ustala wołający na podstawie `asset_source_map.priority`, ten plik jej
    nie zna, patrz moduł `docstring`).
    """

    def __init__(self, providers: list[Guarded]) -> None:
        if not providers:
            raise ValueError("FallbackChain wymaga co najmniej jednego dostawcy")
        self._providers = providers

    async def get_ohlcv(self, symbol: str, start: date, end: date) -> tuple[list[PriceBar], str]:
        return await self._try_chain(
            Capability.OHLCV, lambda provider: provider.get_ohlcv(symbol, start, end)
        )

    async def get_fx(self, currency: str, start: date, end: date) -> tuple[list[FxQuote], str]:
        return await self._try_chain(
            Capability.FX, lambda provider: provider.get_fx(currency, start, end)
        )

    async def get_metadata(self, symbol: str) -> tuple[AssetMetadata | None, str]:
        return await self._try_chain(
            Capability.METADATA, lambda provider: provider.get_metadata(symbol)
        )

    async def _try_chain(
        self,
        capability: Capability,
        call: Callable[[Guarded], Awaitable[_T]],
    ) -> tuple[_T, str]:
        errors: dict[str, str] = {}
        attempted = False
        for provider in self._providers:
            if capability not in provider.supports:
                continue
            attempted = True
            try:
                result = await call(provider)
            except Exception as exc:
                # Łańcuch fallbacku musi przeżyć wyjątek dowolnego kształtu
                # od dowolnego dostawcy (błąd sieci, `ProviderUnavailableError`
                # z `Guarded` przy otwartym obwodzie, błąd parsowania w
                # konkretnym providerze, ...) — zbieramy przyczynę i próbujemy
                # kolejnego; ostateczna porażka całego łańcucha niżej.
                errors[provider.name] = f"{type(exc).__name__}: {exc}"
                logger.warning(
                    "fallback_chain.provider_failed",
                    provider=provider.name,
                    capability=capability.value,
                    error=errors[provider.name],
                )
                continue
            return result, provider.name

        if not attempted:
            errors["_"] = f"żaden dostawca w łańcuchu nie obsługuje możliwości {capability.value}"
        logger.warning(
            "fallback_chain.exhausted",
            capability=capability.value,
            providers=[p.name for p in self._providers],
        )
        raise ProviderUnavailableError(
            f"Wszyscy dostawcy w łańcuchu zawiedli dla możliwości {capability.value}",
            details={"capability": capability.value, "errors": errors},
        )
