"""`StooqProvider` — notowania GPW/indeksy PL z darmowego endpointu CSV
Stooq (plan krok 22, etap 4).

Bez klucza API, ale bez oficjalnego kontraktu: `https://stooq.pl/q/d/l/`
bywa chroniony wyzwaniem anty-bot typu proof-of-work w JavaScript
(zaobserwowane przy budowie tego providera — odpowiedź to strona HTML
zamiast CSV, niemożliwa do rozwiązania po stronie serwera bez przeglądarki).
Traktujemy każdą odpowiedź, która nie zaczyna się od oczekiwanego nagłówka
CSV, jako porażkę tego providera (`ProviderUnavailableError`) — dzięki temu
`FallbackChain` (`fallback_chain.py`) spróbuje kolejnego dostawcy zamiast
dostać cichą pustą listę cen albo próbować parsować HTML jako CSV.

**Brak `close_adj`:** Stooq nie publikuje w tym endpoincie ceny skorygowanej
o dywidendy/splity — `close_adj := close` (CLAUDE.md #4, zasada 6), fakt
odnotowany `structlog.warning` przy każdym niepustym wyniku, żeby był
widoczny w logach ingestii, nie tylko w tym komentarzu.
"""

from __future__ import annotations

import csv
from datetime import date
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

_BASE_URL = "https://stooq.pl/q/d/l/"
_EXPECTED_HEADER = ["Data", "Otwarcie", "Najwyzszy", "Najnizszy", "Zamkniecie", "Wolumen"]


class StooqProvider:
    """`supports = {Capability.OHLCV}` — Stooq nie ma FX ani metadanych w
    tym endpoincie (kursy walut wyłącznie NBP, CLAUDE.md #3.5)."""

    name = "stooq"
    supports = {Capability.OHLCV}

    def __init__(
        self,
        *,
        client: httpx.AsyncClient | None = None,
        timeout: float = 10.0,
        limiter: RateLimiter | None = None,
    ) -> None:
        self._client = client
        self._timeout = timeout
        # Leniwie budowany domyślny limiter (backoff na 429) — nie dotyka
        # sieci/Redisa w konstruktorze, patrz `RateLimiter.__init__`.
        self._limiter = limiter or RateLimiter(self.name, get_settings().rate_limit_stooq)

    async def get_ohlcv(self, symbol: str, start: date, end: date) -> list[PriceBar]:
        params = {
            "s": symbol,
            "d1": start.strftime("%Y%m%d"),
            "d2": end.strftime("%Y%m%d"),
            "i": "d",
        }
        text = await self._fetch(params)
        return self._parse_csv(text, symbol=symbol)

    async def get_fx(self, currency: str, start: date, end: date) -> list[FxQuote]:
        raise NotImplementedError(
            "StooqProvider nie obsługuje FX — Capability.FX nie jest w `supports`, "
            "kursy walut wyłącznie z NBP (CLAUDE.md #3.5)"
        )

    async def get_metadata(self, symbol: str) -> AssetMetadata | None:
        raise NotImplementedError(
            "StooqProvider nie obsługuje metadanych — Capability.METADATA nie jest w `supports`"
        )

    async def _fetch(self, params: dict[str, str]) -> str:
        if self._client is not None:
            response = await get_with_backoff(
                self._client,
                _BASE_URL,
                params=params,
                limiter=self._limiter,
                request_timeout=self._timeout,
            )
            return response.text
        async with httpx.AsyncClient() as client:
            response = await get_with_backoff(
                client,
                _BASE_URL,
                params=params,
                limiter=self._limiter,
                request_timeout=self._timeout,
            )
            return response.text

    def _parse_csv(self, text: str, *, symbol: str) -> list[PriceBar]:
        lines = text.strip().splitlines()
        if not lines or lines[0].split(",") != _EXPECTED_HEADER:
            logger.warning("stooq.unexpected_response", symbol=symbol, head=text[:200])
            raise ProviderUnavailableError(
                f"Stooq zwrócił nieoczekiwaną odpowiedź dla symbolu {symbol!r} "
                "(brak oczekiwanego nagłówka CSV — prawdopodobnie wyzwanie "
                "anty-bot albo nieznany symbol)",
                details={"provider": self.name, "symbol": symbol},
            )

        bars: list[PriceBar] = []
        for row in csv.DictReader(lines):
            try:
                bar_date = date.fromisoformat(row["Data"])
            except (KeyError, ValueError) as exc:
                logger.warning("stooq.row_parse_failed", symbol=symbol, row=row, error=str(exc))
                continue
            try:
                close = decimal_or_none(row.get("Zamkniecie"))
            except InvalidOperation:
                close = None
            if close is None:
                logger.warning("stooq.row_missing_close", symbol=symbol, row=row)
                continue
            bars.append(
                PriceBar(
                    date=bar_date,
                    open=decimal_or_none(row.get("Otwarcie")),
                    high=decimal_or_none(row.get("Najwyzszy")),
                    low=decimal_or_none(row.get("Najnizszy")),
                    close=close,
                    close_adj=close,
                    volume=int_or_none(row.get("Wolumen")),
                )
            )

        if bars:
            logger.warning(
                "stooq.close_adj_unavailable",
                symbol=symbol,
                provider=self.name,
                note="Stooq nie publikuje ceny skorygowanej — close_adj := close",
            )
        return bars
