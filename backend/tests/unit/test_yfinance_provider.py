"""Testy `YFinanceProvider` (`app.modules.marketdata.providers.yfinance`).

Zero sieci — `yfinance` to biblioteka (nie surowe HTTP), więc zamiast
`respx` mockujemy `yf.Ticker` samo (`monkeypatch`, SKILL `data-provider`:
„yfinance/Finnhub trudniej nagrać bez mockowania biblioteki — użyj
unittest.mock/monkeypatch na poziomie klienta HTTP (Finnhub) i na
poziomie yf.Ticker (yfinance)"). Dane w fixture'ach
(`tests/fixtures/providers/yfinance/*.json`) są zbudowane ręcznie wg
realnego kształtu `Ticker.history()`/`Ticker.info` (kolumny
`Open/High/Low/Close/Adj Close/Volume`, `info` jako słownik) — nie są
realnym zrzutem z Yahoo Finance (nieoficjalne API bez łatwego CSV do
pobrania bez samej biblioteki, patrz raport kroku).
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from app.modules.marketdata.providers import yfinance as yfinance_provider
from app.modules.marketdata.providers.yfinance import YFinanceProvider

_FIXTURES = Path(__file__).parent.parent / "fixtures" / "providers" / "yfinance"


class _FakeTicker:
    def __init__(self, symbol: str, *, history: pd.DataFrame, info: dict[str, Any]) -> None:
        self.symbol = symbol
        self._history = history
        self.info = info

    def history(self, *, start: str, end: str, auto_adjust: bool) -> pd.DataFrame:
        assert auto_adjust is False, "musimy prosić o Adj Close osobno od Close (patrz docstring)"
        return self._history


def _history_frame_from_fixture() -> pd.DataFrame:
    raw = json.loads((_FIXTURES / "aapl_history.json").read_text())
    return pd.DataFrame(
        {
            "Open": raw["open"],
            "High": raw["high"],
            "Low": raw["low"],
            "Close": raw["close"],
            "Adj Close": raw["adj_close"],
            "Volume": raw["volume"],
        },
        index=pd.to_datetime(raw["dates"]),
    )


async def test_get_ohlcv_uses_real_adjusted_close_not_close(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    history = _history_frame_from_fixture()
    monkeypatch.setattr(
        yfinance_provider.yf,
        "Ticker",
        lambda symbol: _FakeTicker(symbol, history=history, info={}),
    )
    provider = YFinanceProvider()

    bars = await provider.get_ohlcv("AAPL", date(2026, 7, 20), date(2026, 7, 24))

    assert len(bars) == 5
    first = bars[0]
    assert first.date == date(2026, 7, 20)
    assert first.close == Decimal("220.15")
    assert first.close_adj == Decimal("219.95")
    # yfinance jest jedynym providerem tego kroku, gdzie close != close_adj
    # naprawdę (realna cena skorygowana), patrz docstring modułu.
    assert first.close_adj != first.close
    assert first.volume == 58234100


async def test_get_ohlcv_empty_history_returns_empty_list(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        yfinance_provider.yf,
        "Ticker",
        lambda symbol: _FakeTicker(symbol, history=pd.DataFrame(), info={}),
    )
    provider = YFinanceProvider()

    bars = await provider.get_ohlcv("NIEZNANY", date(2026, 7, 20), date(2026, 7, 24))

    assert bars == []


async def test_get_metadata_returns_sector_and_country_for_equity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    info = json.loads((_FIXTURES / "aapl_info.json").read_text())
    monkeypatch.setattr(
        yfinance_provider.yf,
        "Ticker",
        lambda symbol: _FakeTicker(symbol, history=pd.DataFrame(), info=info),
    )
    provider = YFinanceProvider()

    metadata = await provider.get_metadata("AAPL")

    assert metadata is not None
    assert metadata.name == "Apple Inc."
    assert metadata.sector == "Technology"
    assert metadata.country == "United States"
    assert metadata.asset_class == "EQUITY"


async def test_get_metadata_for_crypto_has_no_sector_or_country_documented_limitation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SKILL `data-provider`: „sektor/kraj tylko dla akcji, dla ETF/krypto
    przybliżenie" — brak `sector`/`country` jest udokumentowanym
    ograniczeniem, nie błędem (`get_metadata` nadal zwraca resztę pól)."""
    info = json.loads((_FIXTURES / "btc_usd_info.json").read_text())
    monkeypatch.setattr(
        yfinance_provider.yf,
        "Ticker",
        lambda symbol: _FakeTicker(symbol, history=pd.DataFrame(), info=info),
    )
    provider = YFinanceProvider()

    metadata = await provider.get_metadata("BTC-USD")

    assert metadata is not None
    assert metadata.sector is None
    assert metadata.country is None
    assert metadata.asset_class == "CRYPTOCURRENCY"


async def test_get_metadata_missing_symbol_in_info_returns_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        yfinance_provider.yf,
        "Ticker",
        lambda symbol: _FakeTicker(symbol, history=pd.DataFrame(), info={}),
    )
    provider = YFinanceProvider()

    metadata = await provider.get_metadata("COS-DZIWNEGO")

    assert metadata is None


async def test_get_fx_is_not_supported() -> None:
    provider = YFinanceProvider()
    with pytest.raises(NotImplementedError):
        await provider.get_fx("USD", date(2026, 7, 1), date(2026, 7, 24))


@pytest.mark.network
async def test_smoke_live_yahoo_finance_returns_recent_aapl_candles() -> None:
    """Test dymny na żywe Yahoo Finance (przez `yfinance`) — wyłączony z CI
    (`-m "not network"`), uruchamiany ręcznie żeby wykryć, gdy `yfinance`
    faktycznie „zamilknie" (SKILL `data-provider`: „nieoficjalne API, potrafi
    milczeć"), ten sam wzorzec co `tests/unit/test_nbp_provider.py`."""
    provider = YFinanceProvider()
    end = date.today()
    start = end - timedelta(days=7)

    bars = await provider.get_ohlcv("AAPL", start, end)

    assert len(bars) >= 1
    assert all(bar.close > 0 for bar in bars)
