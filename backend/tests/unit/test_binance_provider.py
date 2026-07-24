"""Testy `BinanceProvider` (`app.modules.marketdata.providers.binance`).

Zero sieci domyślnie — `btcusdt_ok.json`/`invalid_symbol.json` w
`tests/fixtures/providers/binance/` to **realne** odpowiedzi pobrane raz z
`https://api.binance.com/api/v3/klines` (publiczne REST, bez klucza, dostęp
do sieci był dostępny przy budowie tego providera — patrz raport kroku).
HTTP w testach mimo to przechwycone przez `respx`, żeby testy nie zależały
od sieci przy każdym uruchomieniu.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncGenerator
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
import respx

from app.core.cache import get_redis
from app.core.errors import ProviderUnavailableError
from app.modules.marketdata.providers.binance import BinanceProvider
from app.modules.marketdata.providers.rate_limiter import RateLimiter
from tests.unit._fake_clock import FakeClock

_FIXTURES = Path(__file__).parent.parent / "fixtures" / "providers" / "binance"
_URL = "https://api.binance.com/api/v3/klines"


@pytest.fixture(autouse=True)
async def _cleanup_rate_limiter_keys() -> AsyncGenerator[None, None]:
    yield
    async for key in get_redis().scan_iter("rate_limiter:test-binance-*"):
        await get_redis().delete(key)


def _provider() -> BinanceProvider:
    limiter = RateLimiter(f"test-binance-{uuid.uuid4().hex}", 60, redis=get_redis())
    return BinanceProvider(limiter=limiter)


async def test_get_ohlcv_parses_klines_with_close_adj_equal_to_close() -> None:
    payload = json.loads((_FIXTURES / "btcusdt_ok.json").read_text())
    provider = _provider()

    with respx.mock(assert_all_called=True) as router:
        router.get(_URL).respond(json=payload)
        bars = await provider.get_ohlcv("BTCUSDT", date(2026, 6, 27), date(2026, 6, 30))

    assert len(bars) == len(payload)
    first = bars[0]
    assert first.close == Decimal(payload[0][4])
    # Krypto spot nie ma ceny skorygowanej — close_adj := close (odnotowane
    # jako `info`, nie `warning`, patrz docstring `binance.py`).
    assert first.close_adj == first.close
    assert first.volume == int(Decimal(payload[0][5]))
    assert all(bar.close_adj == bar.close for bar in bars)


async def test_get_ohlcv_invalid_symbol_http_400_raises() -> None:
    """Realny kształt błędu Binance dla nieznanego symbolu — HTTP 400 z
    `{"code": -1121, "msg": "Invalid symbol."}` (pobrane bez klucza z
    `api.binance.com`, patrz raport kroku); `raise_for_status()` w
    `get_with_backoff` rzuca zanim payload trafi do `_parse_klines`."""
    payload = json.loads((_FIXTURES / "invalid_symbol.json").read_text())
    provider = _provider()

    with respx.mock(assert_all_called=True) as router:
        router.get(_URL).respond(status_code=400, json=payload)
        with pytest.raises(httpx.HTTPStatusError):
            await provider.get_ohlcv("NOTREALSYMBOL", date(2026, 7, 1), date(2026, 7, 24))


def test_parse_klines_error_shaped_dict_payload_raises_provider_unavailable() -> None:
    """Test jednostkowy (bez HTTP) dla obronnej gałęzi `_parse_klines`,
    gdyby Binance kiedyś zwrócił kształt błędu przy HTTP 200 zamiast 4xx."""
    provider = _provider()
    with pytest.raises(ProviderUnavailableError):
        provider._parse_klines({"code": -1121, "msg": "Invalid symbol."}, symbol="X")


async def test_get_ohlcv_retries_on_http_429_then_succeeds() -> None:
    payload = json.loads((_FIXTURES / "btcusdt_ok.json").read_text())
    clock = FakeClock()
    limiter = RateLimiter(
        f"test-binance-{uuid.uuid4().hex}",
        60,
        redis=get_redis(),
        clock=clock.time,
        sleep=clock.sleep,
    )
    provider = BinanceProvider(limiter=limiter)

    with respx.mock(assert_all_called=True) as router:
        route = router.get(_URL)
        route.side_effect = [
            httpx.Response(429),
            httpx.Response(200, json=payload),
        ]
        bars = await provider.get_ohlcv("BTCUSDT", date(2026, 6, 27), date(2026, 6, 30))

    assert len(bars) == len(payload)
    assert clock.slept_seconds


async def test_get_fx_and_get_metadata_are_not_supported() -> None:
    provider = _provider()
    with pytest.raises(NotImplementedError):
        await provider.get_fx("USD", date(2026, 7, 1), date(2026, 7, 24))
    with pytest.raises(NotImplementedError):
        await provider.get_metadata("BTCUSDT")


@pytest.mark.network
async def test_smoke_live_binance_api_returns_recent_btcusdt_candles() -> None:
    """Test dymny na żywe `api.binance.com` — wyłączony z CI (`-m "not
    network"`), uruchamiany ręcznie żeby wykryć zmianę kształtu odpowiedzi
    Binance (ten sam wzorzec co `tests/unit/test_nbp_provider.py`)."""
    provider = _provider()
    end = date.today()
    start = end - timedelta(days=5)

    bars = await provider.get_ohlcv("BTCUSDT", start, end)

    assert len(bars) >= 1
    assert all(bar.close_adj == bar.close and bar.close > 0 for bar in bars)
