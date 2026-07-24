"""Testy `FallbackChain` (`app.modules.marketdata.providers.fallback_chain`).

Fake providerzy (nie prawdziwe NBP/Stooq/yfinance — te powstają w krokach
21-22), owinięci prawdziwym `Guarded` (`RateLimiter`/`CircuitBreaker`
backed by Redis, domyślne, hojne limity — te testy nie sprawdzają limitera
ani obwodu, tylko kolejność/fallback samego łańcucha, patrz
`test_rate_limiter.py`/`test_circuit_breaker.py` dla tamtych).
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from datetime import date
from decimal import Decimal

import pytest

from app.core.cache import get_redis
from app.core.errors import ProviderUnavailableError
from app.modules.marketdata.providers.base import AssetMetadata, Capability, FxQuote, PriceBar
from app.modules.marketdata.providers.circuit_breaker import CircuitBreaker
from app.modules.marketdata.providers.fallback_chain import FallbackChain
from app.modules.marketdata.providers.guarded import Guarded
from app.modules.marketdata.providers.rate_limiter import RateLimiter

_SYMBOL = "CDR"
_START = date(2026, 7, 1)
_END = date(2026, 7, 24)

_BAR = PriceBar(
    date=_END,
    open=Decimal("100"),
    high=Decimal("105"),
    low=Decimal("99"),
    close=Decimal("104"),
    close_adj=Decimal("104"),
    volume=1000,
)


class FakeProvider:
    """Provider testowy: zwraca stały wynik albo zawsze rzuca `fail`."""

    def __init__(
        self,
        name: str,
        supports: set[Capability],
        *,
        ohlcv_result: list[PriceBar] | None = None,
        fx_result: list[FxQuote] | None = None,
        metadata_result: AssetMetadata | None = None,
        fail: Exception | None = None,
    ) -> None:
        self.name = name
        self.supports = supports
        self._ohlcv_result = ohlcv_result if ohlcv_result is not None else []
        self._fx_result = fx_result if fx_result is not None else []
        self._metadata_result = metadata_result
        self._fail = fail

    async def get_ohlcv(self, symbol: str, start: date, end: date) -> list[PriceBar]:
        if self._fail is not None:
            raise self._fail
        return self._ohlcv_result

    async def get_fx(self, currency: str, start: date, end: date) -> list[FxQuote]:
        if self._fail is not None:
            raise self._fail
        return self._fx_result

    async def get_metadata(self, symbol: str) -> AssetMetadata | None:
        if self._fail is not None:
            raise self._fail
        return self._metadata_result


def _guard(provider: FakeProvider) -> Guarded:
    key = f"test-chain-{uuid.uuid4().hex}"
    limiter = RateLimiter(key, 60, redis=get_redis())
    breaker = CircuitBreaker(key, failure_threshold=5, reset_timeout=60, redis=get_redis())
    return Guarded(provider, limiter, breaker)


@pytest.fixture(autouse=True)
async def _cleanup_chain_keys() -> AsyncGenerator[None, None]:
    yield
    async for key in get_redis().scan_iter("rate_limiter:test-chain-*"):
        await get_redis().delete(key)
    async for key in get_redis().scan_iter("circuit_breaker:test-chain-*"):
        await get_redis().delete(key)


async def test_fallback_chain_requires_at_least_one_provider() -> None:
    with pytest.raises(ValueError, match="co najmniej jednego"):
        FallbackChain([])


async def test_first_provider_success_is_used_without_trying_others() -> None:
    first = FakeProvider("first", {Capability.OHLCV}, ohlcv_result=[_BAR])
    second = FakeProvider(
        "second", {Capability.OHLCV}, fail=RuntimeError("nie powinno się wywołać")
    )
    chain = FallbackChain([_guard(first), _guard(second)])

    bars, provider_name = await chain.get_ohlcv(_SYMBOL, _START, _END)

    assert bars == [_BAR]
    assert provider_name == "first"


async def test_first_provider_fails_second_succeeds() -> None:
    first = FakeProvider("first", {Capability.OHLCV}, fail=RuntimeError("stooq padło"))
    second = FakeProvider("second", {Capability.OHLCV}, ohlcv_result=[_BAR])
    chain = FallbackChain([_guard(first), _guard(second)])

    bars, provider_name = await chain.get_ohlcv(_SYMBOL, _START, _END)

    assert bars == [_BAR]
    assert provider_name == "second"


async def test_all_providers_fail_raises_provider_unavailable_with_details() -> None:
    first = FakeProvider("first", {Capability.OHLCV}, fail=RuntimeError("stooq padło"))
    second = FakeProvider("second", {Capability.OHLCV}, fail=RuntimeError("yfinance padło"))
    chain = FallbackChain([_guard(first), _guard(second)])

    with pytest.raises(ProviderUnavailableError) as exc_info:
        await chain.get_ohlcv(_SYMBOL, _START, _END)

    errors = exc_info.value.details["errors"] if exc_info.value.details else {}
    assert set(errors) == {"first", "second"}


async def test_provider_without_capability_is_skipped() -> None:
    fx_only = FakeProvider("fx-only", {Capability.FX})
    ohlcv_provider = FakeProvider("ohlcv", {Capability.OHLCV}, ohlcv_result=[_BAR])
    chain = FallbackChain([_guard(fx_only), _guard(ohlcv_provider)])

    bars, provider_name = await chain.get_ohlcv(_SYMBOL, _START, _END)

    assert bars == [_BAR]
    assert provider_name == "ohlcv"


async def test_no_provider_supports_capability_raises_provider_unavailable() -> None:
    fx_only = FakeProvider("fx-only", {Capability.FX})
    chain = FallbackChain([_guard(fx_only)])

    with pytest.raises(ProviderUnavailableError, match="ohlcv"):
        await chain.get_ohlcv(_SYMBOL, _START, _END)


async def test_get_fx_and_get_metadata_also_return_provider_name() -> None:
    fx_quote = FxQuote(currency="USD", date=_END, rate_pln=Decimal("4.05"))
    metadata = AssetMetadata(
        symbol=_SYMBOL, name="CD Projekt", sector="Gaming", country="PL", asset_class="stock"
    )
    fx_provider = FakeProvider(
        "nbp", {Capability.FX, Capability.METADATA}, fx_result=[fx_quote], metadata_result=metadata
    )
    chain = FallbackChain([_guard(fx_provider)])

    fx_rates, fx_provider_name = await chain.get_fx("USD", _START, _END)
    meta, meta_provider_name = await chain.get_metadata(_SYMBOL)

    assert fx_rates == [fx_quote]
    assert fx_provider_name == "nbp"
    assert meta == metadata
    assert meta_provider_name == "nbp"
