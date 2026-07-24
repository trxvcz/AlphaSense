"""`YFinanceProvider` — rynki zagraniczne (OHLCV) i metadane aktywów (plan
krok 22, etap 4), przez pakiet `yfinance` (nieoficjalny klient Yahoo
Finance, `requirements.txt`).

**Blokujące I/O:** `yfinance` nie ma natywnego async API — `Ticker.history`/
`Ticker.info` robią synchroniczne żądania HTTP wewnątrz. Reguła projektu
(zero blokującego I/O w handlerach/jobach, `pyproject.toml` lint `ASYNC`)
wymaga owinięcia w `asyncio.to_thread`, żeby nie blokować event loopa API
ani workera — stąd każda publiczna metoda tego providera deleguje do
prywatnej, synchronicznej implementacji przez `asyncio.to_thread`.

**`close_adj` — tu akurat naprawdę dostępny:** w odróżnieniu od Stooq/
Finnhub, Yahoo Finance publikuje realną cenę skorygowaną o dywidendy/splity
(kolumna `Adj Close`, dostępna gdy `history(..., auto_adjust=False)` —
świadomie **nie** korzystamy z domyślnego `auto_adjust=True`, bo wtedy
`yfinance` nadpisuje `Close` samą skorygowaną wartością i tracimy dostęp
do surowego zamknięcia, którego też chcemy dla `Price.close`).

**Symbol Yahoo Finance:** akcje jak w Yahoo (`AAPL`, `MSFT`), krypto jako
para z myślnikiem (`BTC-USD`) — patrz `binance.py` (fallback dla `CRYPTO`).
Symbol pochodzi z `asset_source_map.provider_symbol`, nigdy sklejany tutaj.

**Metadane — udokumentowane ograniczenie:** `Ticker.info` daje sensowny
`sector`/`country` tylko dla akcji; dla ETF/krypto te pola bywają puste
albo nieobecne w słowniku — to nie błąd, `get_metadata` po prostu zwraca to,
co jest, z `None` tam, gdzie brak (SKILL `data-provider`, tabela „Specyfika
źródeł").
"""

from __future__ import annotations

import asyncio
import math
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import structlog
import yfinance as yf

from app.modules.marketdata.providers.base import AssetMetadata, Capability, FxQuote, PriceBar

logger = structlog.get_logger(__name__)


def _decimal_or_none(value: object) -> Decimal | None:
    """`pandas`/`yfinance` zwracają `float` (czasem `numpy.float64`,
    czasem `nan` dla brakujących komórek) — `str(value)` przed `Decimal`,
    żeby uniknąć bezpośredniego rzutowania błędu binarnego `float`
    (CLAUDE.md #3.1), `nan`/`None` mapowane na `None`.
    """
    if value is None:
        return None
    try:
        float_value = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if math.isnan(float_value):
        return None
    return Decimal(str(float_value))


def _int_or_none(value: object) -> int | None:
    decimal_value = _decimal_or_none(value)
    return int(decimal_value) if decimal_value is not None else None


class YFinanceProvider:
    """`supports = {Capability.OHLCV, Capability.METADATA}`."""

    name = "yfinance"
    supports = {Capability.OHLCV, Capability.METADATA}

    async def get_ohlcv(self, symbol: str, start: date, end: date) -> list[PriceBar]:
        return await asyncio.to_thread(self._get_ohlcv_sync, symbol, start, end)

    async def get_fx(self, currency: str, start: date, end: date) -> list[FxQuote]:
        raise NotImplementedError(
            "YFinanceProvider nie obsługuje FX — Capability.FX nie jest w `supports`, "
            "kursy walut wyłącznie z NBP (CLAUDE.md #3.5)"
        )

    async def get_metadata(self, symbol: str) -> AssetMetadata | None:
        return await asyncio.to_thread(self._get_metadata_sync, symbol)

    def _get_ohlcv_sync(self, symbol: str, start: date, end: date) -> list[PriceBar]:
        ticker = yf.Ticker(symbol)
        # `history(end=...)` jest wyłączny (nie obejmuje dnia `end`) —
        # +1 dzień, żeby `end` faktycznie trafił do wyniku.
        history = ticker.history(
            start=start.isoformat(),
            end=(end + timedelta(days=1)).isoformat(),
            auto_adjust=False,
        )
        if history is None or history.empty:
            logger.warning("yfinance.empty_history", symbol=symbol, start=str(start), end=str(end))
            return []

        bars: list[PriceBar] = []
        for index, row in history.iterrows():
            bar_date = index.date() if hasattr(index, "date") else index
            close = _decimal_or_none(row.get("Close"))
            close_adj = _decimal_or_none(row.get("Adj Close"))
            if close is None:
                logger.warning("yfinance.row_missing_close", symbol=symbol, date=str(bar_date))
                continue
            if close_adj is None:
                # Nie powinno się zdarzyć z `auto_adjust=False` na akcjach,
                # ale np. niektóre indeksy/surowce nie mają `Adj Close` —
                # spójne z regułą 6 (CLAUDE.md #4): odnotuj i podstaw `close`.
                logger.warning(
                    "yfinance.close_adj_unavailable",
                    symbol=symbol,
                    date=str(bar_date),
                    note="brak `Adj Close` w odpowiedzi — close_adj := close",
                )
                close_adj = close
            bars.append(
                PriceBar(
                    date=bar_date,
                    open=_decimal_or_none(row.get("Open")),
                    high=_decimal_or_none(row.get("High")),
                    low=_decimal_or_none(row.get("Low")),
                    close=close,
                    close_adj=close_adj,
                    volume=_int_or_none(row.get("Volume")),
                )
            )
        return bars

    def _get_metadata_sync(self, symbol: str) -> AssetMetadata | None:
        ticker = yf.Ticker(symbol)
        info: dict[str, Any] | None = ticker.info
        if not info or info.get("symbol") is None:
            logger.warning("yfinance.metadata_unavailable", symbol=symbol)
            return None
        name = info.get("longName") or info.get("shortName") or symbol
        return AssetMetadata(
            symbol=symbol,
            name=name,
            # `sector`/`country` bywają nieobecne dla ETF/krypto — udokumentowane
            # ograniczenie, nie błąd (patrz docstring modułu).
            sector=info.get("sector"),
            country=info.get("country"),
            asset_class=info.get("quoteType"),
        )
