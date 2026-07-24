"""Testy `StooqProvider` (`app.modules.marketdata.providers.stooq`).

Zero sieci — CSV nagrane w `tests/fixtures/providers/stooq/`. `cdr_ok.csv`
zbudowany ręcznie wg udokumentowanego formatu Stooq (`Data,Otwarcie,
Najwyzszy,Najnizszy,Zamkniecie,Wolumen`): próba realnego pobrania przy
budowie tego providera trafiła na wyzwanie anty-bot (JS proof-of-work)
zamiast CSV — patrz docstring `stooq.py`. `unknown_symbol.csv` to
najbliższe odwzorowanie realnej odpowiedzi Stooq dla nieznanego symbolu
(„Brak danych (Kod błędu 999)").

HTTP przechwycone przez `respx` (ten sam wzorzec co
`tests/integration/test_auth_oauth.py`), zero realnych wywołań do
`stooq.pl`.
"""

from __future__ import annotations

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
from app.modules.marketdata.providers.rate_limiter import RateLimiter
from app.modules.marketdata.providers.stooq import StooqProvider
from tests.unit._fake_clock import FakeClock

_FIXTURES = Path(__file__).parent.parent / "fixtures" / "providers" / "stooq"
_URL = "https://stooq.pl/q/d/l/"


@pytest.fixture(autouse=True)
async def _cleanup_rate_limiter_keys() -> AsyncGenerator[None, None]:
    yield
    async for key in get_redis().scan_iter("rate_limiter:test-stooq-*"):
        await get_redis().delete(key)


def _provider() -> StooqProvider:
    limiter = RateLimiter(f"test-stooq-{uuid.uuid4().hex}", 60, redis=get_redis())
    return StooqProvider(limiter=limiter)


async def test_get_ohlcv_parses_csv_with_close_adj_equal_to_close() -> None:
    body = (_FIXTURES / "cdr_ok.csv").read_text()
    provider = _provider()

    with respx.mock(assert_all_called=True) as router:
        router.get(_URL).respond(text=body)
        bars = await provider.get_ohlcv("cdr", date(2026, 7, 20), date(2026, 7, 24))

    assert len(bars) == 5
    first = bars[0]
    assert first.date == date(2026, 7, 20)
    assert first.open == Decimal("120.50")
    assert first.high == Decimal("122.80")
    assert first.low == Decimal("119.90")
    assert first.close == Decimal("121.40")
    # Stooq nie ma close_adj — reguła 6 (CLAUDE.md #4): close_adj := close.
    assert first.close_adj == first.close
    assert first.volume == 185340
    assert all(bar.close_adj == bar.close for bar in bars)


async def test_get_ohlcv_unknown_symbol_raises_provider_unavailable() -> None:
    body = (_FIXTURES / "unknown_symbol.csv").read_text()
    provider = _provider()

    with respx.mock(assert_all_called=True) as router:
        router.get(_URL).respond(text=body)
        with pytest.raises(ProviderUnavailableError):
            await provider.get_ohlcv("nieistniejacysymbol", date(2026, 7, 1), date(2026, 7, 24))


async def test_get_ohlcv_anti_bot_html_challenge_raises_provider_unavailable() -> None:
    """Realny incydent zaobserwowany przy budowie tego providera: zamiast
    CSV, HTML z wyzwaniem JS proof-of-work — musi zostać potraktowany jako
    porażka providera (nie próba parsowania HTML jako CSV)."""
    html = (
        '<!DOCTYPE html><html><head><meta charset="utf-8">'
        '<meta name="robots" content="noindex,nofollow"></head><body>'
        "<noscript>This site requires JavaScript to verify your browser.</noscript>"
        "</body></html>"
    )
    provider = _provider()

    with respx.mock(assert_all_called=True) as router:
        router.get(_URL).respond(text=html)
        with pytest.raises(ProviderUnavailableError):
            await provider.get_ohlcv("cdr", date(2026, 7, 1), date(2026, 7, 24))


async def test_get_ohlcv_retries_on_http_429_then_succeeds() -> None:
    body = (_FIXTURES / "cdr_ok.csv").read_text()
    clock = FakeClock()
    limiter = RateLimiter(
        f"test-stooq-{uuid.uuid4().hex}",
        60,
        redis=get_redis(),
        clock=clock.time,
        sleep=clock.sleep,
    )
    provider = StooqProvider(limiter=limiter)

    with respx.mock(assert_all_called=True) as router:
        route = router.get(_URL)
        route.side_effect = [
            httpx.Response(429),
            httpx.Response(200, text=body),
        ]
        bars = await provider.get_ohlcv("cdr", date(2026, 7, 20), date(2026, 7, 24))

    assert len(bars) == 5
    assert clock.slept_seconds, "429 powinno wywołać backoff (choćby jedno oczekiwanie)"


async def test_get_fx_and_get_metadata_are_not_supported() -> None:
    provider = _provider()
    with pytest.raises(NotImplementedError):
        await provider.get_fx("USD", date(2026, 7, 1), date(2026, 7, 24))
    with pytest.raises(NotImplementedError):
        await provider.get_metadata("cdr")
