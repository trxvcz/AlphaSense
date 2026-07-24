"""Testy `FinnhubProvider` (`app.modules.marketdata.providers.finnhub`).

Zero sieci — JSON nagrane ręcznie w `tests/fixtures/providers/finnhub/` wg
udokumentowanego kształtu odpowiedzi `/stock/candle` (klucz nie jest
darmowy do założenia w tym środowisku, stąd fixture ręczny, nie pobrany —
patrz raport kroku). HTTP przechwycone przez `respx`.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncGenerator
from datetime import date
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
import respx

from app.core.cache import get_redis
from app.core.errors import ProviderUnavailableError
from app.modules.marketdata.providers.finnhub import FinnhubProvider
from app.modules.marketdata.providers.rate_limiter import RateLimiter
from tests.unit._fake_clock import FakeClock

_FIXTURES = Path(__file__).parent.parent / "fixtures" / "providers" / "finnhub"
_URL = "https://finnhub.io/api/v1/stock/candle"


@pytest.fixture(autouse=True)
async def _cleanup_rate_limiter_keys() -> AsyncGenerator[None, None]:
    yield
    async for key in get_redis().scan_iter("rate_limiter:test-finnhub-*"):
        await get_redis().delete(key)


def _provider(*, api_key: str | None = "test-key") -> FinnhubProvider:
    limiter = RateLimiter(f"test-finnhub-{uuid.uuid4().hex}", 60, redis=get_redis())
    return FinnhubProvider(limiter=limiter, api_key=api_key)


async def test_get_ohlcv_parses_candles_with_close_adj_equal_to_close() -> None:
    payload = json.loads((_FIXTURES / "aapl_ok.json").read_text())
    provider = _provider()

    with respx.mock(assert_all_called=True) as router:
        router.get(_URL).respond(json=payload)
        bars = await provider.get_ohlcv("AAPL", date(2026, 7, 20), date(2026, 7, 24))

    assert len(bars) == 5
    first = bars[0]
    assert first.close == Decimal("220.15")
    assert first.close_adj == first.close  # brak adjusted close w darmowym planie
    assert first.volume == 58234100
    assert all(bar.close_adj == bar.close for bar in bars)


async def test_get_ohlcv_no_data_returns_empty_list_not_error() -> None:
    """`s == "no_data"` = brak notowań w zakresie (np. święta) — nie błąd,
    SKILL `data-provider` reguła 6."""
    payload = json.loads((_FIXTURES / "no_data.json").read_text())
    provider = _provider()

    with respx.mock(assert_all_called=True) as router:
        router.get(_URL).respond(json=payload)
        bars = await provider.get_ohlcv("UNKNOWN", date(2026, 7, 1), date(2026, 7, 2))

    assert bars == []


async def test_get_ohlcv_missing_api_key_raises_provider_unavailable_without_http_call() -> None:
    provider = _provider(api_key="")

    with respx.mock(assert_all_called=False) as router:
        route = router.get(_URL)
        with pytest.raises(ProviderUnavailableError):
            await provider.get_ohlcv("AAPL", date(2026, 7, 1), date(2026, 7, 24))
        assert route.call_count == 0


async def test_get_ohlcv_retries_on_http_429_then_succeeds() -> None:
    payload = json.loads((_FIXTURES / "rate_limited_then_ok.json").read_text())
    clock = FakeClock()
    limiter = RateLimiter(
        f"test-finnhub-{uuid.uuid4().hex}",
        60,
        redis=get_redis(),
        clock=clock.time,
        sleep=clock.sleep,
    )
    provider = FinnhubProvider(limiter=limiter, api_key="test-key")

    with respx.mock(assert_all_called=True) as router:
        route = router.get(_URL)
        route.side_effect = [
            httpx.Response(429),
            httpx.Response(200, json=payload),
        ]
        bars = await provider.get_ohlcv("AAPL", date(2026, 7, 24), date(2026, 7, 24))

    assert len(bars) == 1
    assert clock.slept_seconds


async def test_get_fx_and_get_metadata_are_not_supported() -> None:
    provider = _provider()
    with pytest.raises(NotImplementedError):
        await provider.get_fx("USD", date(2026, 7, 1), date(2026, 7, 24))
    with pytest.raises(NotImplementedError):
        await provider.get_metadata("AAPL")
