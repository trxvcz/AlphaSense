"""`BinanceProvider` — główny dostawca OHLCV dla rynku `CRYPTO` (plan krok
22, etap 4). REST publiczne `https://api.binance.com/api/v3/klines`,
**bez klucza API** (limit darmowy oparty o wagę zapytań, nie o klucz).

**Zamiana CoinGecko → Binance**, ustalona z użytkownikiem: CoinGecko
wyczerpało darmowy plan (patrz zadanie/`.claude/skills/data-provider/
SKILL.md`, wiersz „CoinGecko" w tabeli jest już nieaktualny — zaktualizowany
w tym samym kroku). Symbol Binance to para (`BTCUSDT`, nie identyfikator
CoinGecko typu `bitcoin`) — jak zawsze, ten symbol pochodzi wyłącznie z
`asset_source_map.provider_symbol` (`provider="binance"`), nigdy sklejany
w kodzie.

Fallback dla krypto: `YFinanceProvider` z symbolem `BTC-USD` (Yahoo Finance
ma własną notację dla par krypto) — kompozycja przykładowa w
`service.py::build_fallback_chain`.

Binance nie publikuje osobnej „ceny skorygowanej" dla par spot (nie ma tu
tradycyjnych dywidend/splitów akcyjnych) — `close_adj := close`, odnotowane
na poziomie `info` (nie `warning`, w odróżnieniu od Stooq/Finnhub): to nie
ograniczenie API, tylko właściwość klasy aktywa (CLAUDE.md #4, zasada 6
i dalej wymaga odnotowania faktu, nie precyzuje poziomu logu).
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time
from decimal import InvalidOperation

import httpx
import structlog

from app.core.config import get_settings
from app.core.errors import ProviderUnavailableError
from app.modules.marketdata.providers.base import AssetMetadata, Capability, FxQuote, PriceBar
from app.modules.marketdata.providers.http_client import decimal_or_none, get_with_backoff
from app.modules.marketdata.providers.rate_limiter import RateLimiter

logger = structlog.get_logger(__name__)

_BASE_URL = "https://api.binance.com/api/v3/klines"
# Binance ogranicza max 1000 świec na żądanie — zakresy dłuższe niż to
# (ingestia EOD zwykle pyta o kilka dni, nie o lata) obetnie samo API,
# licząc od `startTime`; paginacja to poza zakresem tego kroku (ingestia
# EOD kroku 23 pyta o krótkie okna).
_MAX_KLINES = 1000


def _to_millis(day: date, *, end_of_day: bool) -> int:
    clock = time(23, 59, 59) if end_of_day else time(0, 0, 0)
    return int(datetime.combine(day, clock, tzinfo=UTC).timestamp() * 1000)


class BinanceProvider:
    """`supports = {Capability.OHLCV}` — Binance nie ma metadanych/FX
    użytecznych dla naszego modelu (kursy walut wyłącznie z NBP)."""

    name = "binance"
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
        self._limiter = limiter or RateLimiter(self.name, get_settings().rate_limit_binance)

    async def get_ohlcv(self, symbol: str, start: date, end: date) -> list[PriceBar]:
        params = {
            "symbol": symbol,
            "interval": "1d",
            "startTime": str(_to_millis(start, end_of_day=False)),
            "endTime": str(_to_millis(end, end_of_day=True)),
            "limit": str(_MAX_KLINES),
        }
        payload = await self._fetch(params)
        return self._parse_klines(payload, symbol=symbol)

    async def get_fx(self, currency: str, start: date, end: date) -> list[FxQuote]:
        raise NotImplementedError(
            "BinanceProvider nie obsługuje FX — Capability.FX nie jest w `supports`, "
            "kursy walut wyłącznie z NBP (CLAUDE.md #3.5)"
        )

    async def get_metadata(self, symbol: str) -> AssetMetadata | None:
        raise NotImplementedError(
            "BinanceProvider nie obsługuje metadanych — Capability.METADATA nie jest w `supports`"
        )

    async def _fetch(self, params: dict[str, str]) -> object:
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
        result: object = response.json()
        return result

    def _parse_klines(self, payload: object, *, symbol: str) -> list[PriceBar]:
        if isinstance(payload, dict):
            # Kształt błędu Binance: {"code": -1121, "msg": "Invalid symbol."}
            logger.warning("binance.error_response", symbol=symbol, payload=payload)
            raise ProviderUnavailableError(
                f"Binance zwrócił błąd dla symbolu {symbol!r}: {payload.get('msg')}",
                details={"provider": self.name, "symbol": symbol, "code": payload.get("code")},
            )
        if not isinstance(payload, list):
            logger.warning(
                "binance.unexpected_payload", symbol=symbol, payload_type=type(payload).__name__
            )
            raise ProviderUnavailableError(
                f"Binance zwrócił nieoczekiwany kształt odpowiedzi dla {symbol!r}",
                details={"provider": self.name, "symbol": symbol},
            )

        bars: list[PriceBar] = []
        for row in payload:
            try:
                open_time_ms = int(row[0])
                bar_date = datetime.fromtimestamp(open_time_ms / 1000, tz=UTC).date()
                close = decimal_or_none(row[4])
            except (IndexError, TypeError, ValueError, InvalidOperation, OSError) as exc:
                logger.warning("binance.row_parse_failed", symbol=symbol, row=row, error=str(exc))
                continue
            if close is None:
                logger.warning("binance.row_missing_close", symbol=symbol, row=row)
                continue
            bars.append(
                PriceBar(
                    date=bar_date,
                    open=decimal_or_none(row[1]),
                    high=decimal_or_none(row[2]),
                    low=decimal_or_none(row[3]),
                    close=close,
                    close_adj=close,
                    volume=_volume_int(row[5]),
                )
            )

        if bars:
            logger.info(
                "binance.close_adj_is_close",
                symbol=symbol,
                provider=self.name,
                note="Pary spot krypto nie mają ceny skorygowanej — close_adj := close",
            )
        return bars


def _volume_int(raw: str | float | int | None) -> int | None:
    value = decimal_or_none(raw)
    return int(value) if value is not None else None
