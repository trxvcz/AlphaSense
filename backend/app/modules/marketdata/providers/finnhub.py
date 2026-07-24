"""`FinnhubProvider` — fallback OHLCV dla rynków zagranicznych (plan krok 22,
etap 4), REST `https://finnhub.io/api/v1/stock/candle`.

**Brak klucza API — decyzja:** Finnhub wymaga `FINNHUB_API_KEY` (darmowy,
ale trzeba go założyć — `docs/plan-dzialania-portfel-v2.md` krok 0). Zamiast
failować import/inicjalizację modułu (co zepsułoby budowę `FallbackChain`
w ogóle, nawet gdy Finnhub jest jednym z kilku dostawców w łańcuchu),
`FinnhubProvider` daje się utworzyć zawsze — dopiero `get_ohlcv` sprawdza
klucz i, jeśli go brak, rzuca `ProviderUnavailableError` **przy pierwszym
wywołaniu** (spójne z resztą providerów: `FallbackChain` łapie dowolny
wyjątek i próbuje kolejnego dostawcy, patrz `fallback_chain.py`).
Dodatkowo — dla wołających, którzy komponują łańcuch świadomie (patrz
`service.py::build_fallback_chain`, przykład dla workera kroku 23) —
zalecane jest w ogóle pominąć `FinnhubProvider` w łańcuchu, gdy
`settings.finnhub_api_key` jest puste, żeby nie marnować próby/logów na
pewną porażkę. Obie warstwy razem: provider nie wywala się przy budowie,
kompozycja (gdy jej autor tak zdecyduje) może dodatkowo go przycinać.

Darmowy plan Finnhub (`/stock/candle`) nie zwraca ceny skorygowanej o
dywidendy/splity — tak samo jak Stooq, `close_adj := close` i odnotowane
(CLAUDE.md #4, zasada 6).
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time
from decimal import InvalidOperation

import httpx
import structlog

from app.core.config import get_settings
from app.core.errors import ProviderUnavailableError
from app.modules.marketdata.providers.base import AssetMetadata, Capability, FxQuote, PriceBar
from app.modules.marketdata.providers.http_client import (
    decimal_or_none,
    get_with_backoff,
    int_or_none,
)
from app.modules.marketdata.providers.rate_limiter import RateLimiter

logger = structlog.get_logger(__name__)

_BASE_URL = "https://finnhub.io/api/v1/stock/candle"


def _to_unix(day: date, *, end_of_day: bool) -> int:
    clock = time(23, 59, 59) if end_of_day else time(0, 0, 0)
    return int(datetime.combine(day, clock, tzinfo=UTC).timestamp())


class FinnhubProvider:
    """`supports = {Capability.OHLCV}` — fallback dla zagranicy (SKILL
    `data-provider`), dywidendy poza zakresem tego kroku."""

    name = "finnhub"
    supports = {Capability.OHLCV}

    def __init__(
        self,
        *,
        client: httpx.AsyncClient | None = None,
        timeout: float = 10.0,
        limiter: RateLimiter | None = None,
        api_key: str | None = None,
    ) -> None:
        self._client = client
        self._timeout = timeout
        self._limiter = limiter or RateLimiter(self.name, get_settings().rate_limit_finnhub)
        # `None` = czytaj leniwie z `get_settings()` przy każdym wywołaniu
        # (żeby testy mogły nadpisać `Settings` bez rekonstrukcji providera,
        # i żeby produkcyjny provider zawsze widział aktualną wartość).
        self._api_key = api_key

    async def get_ohlcv(self, symbol: str, start: date, end: date) -> list[PriceBar]:
        api_key = self._api_key if self._api_key is not None else get_settings().finnhub_api_key
        if not api_key:
            logger.warning("finnhub.missing_api_key", symbol=symbol)
            raise ProviderUnavailableError(
                "Finnhub: brak skonfigurowanego FINNHUB_API_KEY",
                details={"provider": self.name, "symbol": symbol},
            )
        params = {
            "symbol": symbol,
            "resolution": "D",
            "from": str(_to_unix(start, end_of_day=False)),
            "to": str(_to_unix(end, end_of_day=True)),
            "token": api_key,
        }
        payload = await self._fetch(params)
        return self._parse_payload(payload, symbol=symbol)

    async def get_fx(self, currency: str, start: date, end: date) -> list[FxQuote]:
        raise NotImplementedError(
            "FinnhubProvider nie obsługuje FX — Capability.FX nie jest w `supports`, "
            "kursy walut wyłącznie z NBP (CLAUDE.md #3.5)"
        )

    async def get_metadata(self, symbol: str) -> AssetMetadata | None:
        raise NotImplementedError(
            "FinnhubProvider nie obsługuje metadanych w tym kroku — "
            "Capability.METADATA nie jest w `supports`"
        )

    async def _fetch(self, params: dict[str, str]) -> dict[str, object]:
        if self._client is not None:
            response = await get_with_backoff(
                self._client,
                _BASE_URL,
                params=params,
                limiter=self._limiter,
                request_timeout=self._timeout,
            )
        else:
            async with httpx.AsyncClient() as client:
                response = await get_with_backoff(
                    client,
                    _BASE_URL,
                    params=params,
                    limiter=self._limiter,
                    request_timeout=self._timeout,
                )
        payload: dict[str, object] = response.json()
        return payload

    def _parse_payload(self, payload: dict[str, object], *, symbol: str) -> list[PriceBar]:
        status = payload.get("s")
        if status == "no_data":
            # Symbol poprawny, po prostu brak notowań w zadanym zakresie
            # (np. samo święto/weekend) — to nie błąd (SKILL `data-provider`,
            # reguła 6).
            return []
        if status != "ok":
            logger.warning("finnhub.unexpected_status", symbol=symbol, status=status)
            raise ProviderUnavailableError(
                f"Finnhub zwrócił status {status!r} dla symbolu {symbol!r}",
                details={"provider": self.name, "symbol": symbol, "status": status},
            )

        closes = payload.get("c") or []
        opens = payload.get("o") or []
        highs = payload.get("h") or []
        lows = payload.get("l") or []
        volumes = payload.get("v") or []
        timestamps = payload.get("t") or []
        if not isinstance(timestamps, list):
            timestamps = []

        bars: list[PriceBar] = []
        for i, ts in enumerate(timestamps):
            try:
                bar_date = datetime.fromtimestamp(int(ts), tz=UTC).date()
                close = decimal_or_none(_at(closes, i))
            except (ValueError, OSError, InvalidOperation):
                close = None
            if close is None:
                logger.warning("finnhub.row_parse_failed", symbol=symbol, index=i)
                continue
            bars.append(
                PriceBar(
                    date=bar_date,
                    open=decimal_or_none(_at(opens, i)),
                    high=decimal_or_none(_at(highs, i)),
                    low=decimal_or_none(_at(lows, i)),
                    close=close,
                    close_adj=close,
                    volume=int_or_none(_at(volumes, i)),
                )
            )

        if bars:
            logger.warning(
                "finnhub.close_adj_unavailable",
                symbol=symbol,
                provider=self.name,
                note="Darmowy plan Finnhub nie zwraca ceny skorygowanej — close_adj := close",
            )
        return bars


def _at(values: object, index: int) -> str | float | int | None:
    """Bezpieczny dostęp do `payload["c"|"o"|"h"|"l"|"v"][index]` — `payload`
    to `dict[str, object]`, więc mypy nie zna kształtu list liczb, jakie
    Finnhub tam trzyma; zawężamy tu jawnie do typów, jakich oczekują
    `decimal_or_none`/`int_or_none` (`http_client.py`), zamiast przepychać
    surowe `object` dalej.
    """
    if not isinstance(values, list) or index >= len(values):
        return None
    value = values[index]
    if isinstance(value, str | float | int) and not isinstance(value, bool):
        return value
    return None
