"""Testy `RateLimiter` (`app.modules.marketdata.providers.rate_limiter`).

Stan limitera żyje w Redisie (ten sam `REDIS_URL` co reszta stacku testowego
— patrz `tests/integration/test_rate_limit.py` dla analogicznego uzasadnienia
„to nie jest test „network", zero wywołań do sieci zewnętrznej"), ale zegar
i uśpienie są wstrzyknięte (`FakeClock`, `tests/unit/_fake_clock.py`) — testy
kończą się natychmiast, bez prawdziwego oczekiwania na upływ okna.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator

import pytest

from app.core.cache import get_redis
from app.core.errors import ProviderUnavailableError
from app.modules.marketdata.providers.clock import ClockFn, SleepFn
from app.modules.marketdata.providers.rate_limiter import RateLimiter
from tests.unit._fake_clock import FakeClock


def _make_limiter(
    requests_per_minute: int,
    *,
    clock: ClockFn,
    sleep: SleepFn,
    max_retries: int = 5,
    base_backoff_seconds: float = 1.0,
) -> tuple[RateLimiter, str]:
    provider = f"test-provider-{uuid.uuid4().hex}"
    limiter = RateLimiter(
        provider,
        requests_per_minute,
        redis=get_redis(),
        clock=clock,
        sleep=sleep,
        max_retries=max_retries,
        base_backoff_seconds=base_backoff_seconds,
    )
    return limiter, provider


@pytest.fixture(autouse=True)
async def _cleanup_rate_limiter_keys() -> AsyncGenerator[None, None]:
    yield
    async for key in get_redis().scan_iter("rate_limiter:test-provider-*"):
        await get_redis().delete(key)


async def test_requests_within_limit_do_not_wait() -> None:
    """`N` żądań w oknie (`requests_per_minute=N`) — żadne nie czeka."""
    clock = FakeClock()
    limiter, _ = _make_limiter(3, clock=clock.time, sleep=clock.sleep)

    for _ in range(3):
        await limiter.acquire()

    assert clock.slept_seconds == []


async def test_request_over_limit_waits_for_refill() -> None:
    """`N+1`-sze żądanie w tym samym oknie musi poczekać na uzupełnienie kubełka."""
    clock = FakeClock()
    limiter, _ = _make_limiter(2, clock=clock.time, sleep=clock.sleep)

    await limiter.acquire()
    await limiter.acquire()
    # Trzeci token w tej samej "chwili" zegara nie jest jeszcze dostępny —
    # `acquire()` musi poczekać (sztuczny `sleep`, który tylko przesuwa zegar).
    await limiter.acquire()

    assert clock.slept_seconds, "trzecie żądanie w oknie 2/min powinno czekać"
    assert all(seconds > 0 for seconds in clock.slept_seconds)


async def test_bucket_refills_after_full_window() -> None:
    """Po odczekaniu pełnej minuty kubełek jest znów pełny — kolejne `N`
    żądań nie czeka."""
    clock = FakeClock()
    limiter, _ = _make_limiter(2, clock=clock.time, sleep=clock.sleep)

    await limiter.acquire()
    await limiter.acquire()
    clock.advance(60.0)

    await limiter.acquire()
    await limiter.acquire()

    assert clock.slept_seconds == []


async def test_rate_limiter_rejects_non_positive_requests_per_minute() -> None:
    with pytest.raises(ValueError, match="requests_per_minute"):
        RateLimiter("test-provider-invalid", 0, redis=get_redis())


async def test_backoff_sleeps_with_growing_delay_within_bounds() -> None:
    """Kolejne próby po HTTP 429 czekają coraz dłużej, w granicach
    `[base * 2**attempt, base * 2**attempt + base]` (baza + jitter)."""
    clock = FakeClock()
    base = 1.0
    limiter, _ = _make_limiter(
        60, clock=clock.time, sleep=clock.sleep, max_retries=5, base_backoff_seconds=base
    )

    await limiter.backoff(0)
    await limiter.backoff(1)
    await limiter.backoff(2)

    assert len(clock.slept_seconds) == 3
    for attempt, delay in enumerate(clock.slept_seconds):
        lower = base * (2**attempt)
        upper = lower + base
        assert lower <= delay <= upper


async def test_backoff_raises_provider_unavailable_after_max_retries() -> None:
    clock = FakeClock()
    limiter, provider = _make_limiter(
        60, clock=clock.time, sleep=clock.sleep, max_retries=2, base_backoff_seconds=0.01
    )

    await limiter.backoff(0)
    await limiter.backoff(1)

    with pytest.raises(ProviderUnavailableError) as exc_info:
        await limiter.backoff(2)

    assert exc_info.value.details is not None
    assert exc_info.value.details["provider"] == provider


async def test_bucket_state_is_visible_across_independent_instances() -> None:
    """Stan kubełka musi żyć w Redisie, nie w pamięci procesu (docstring
    modułu) — dwie niezależne instancje z tą samą nazwą dostawcy symulują
    tu proces przed i po restarcie workera.
    """
    provider = f"test-provider-{uuid.uuid4().hex}"
    clock = FakeClock()
    limiter_before_restart = RateLimiter(
        provider, 2, redis=get_redis(), clock=clock.time, sleep=clock.sleep
    )

    # Wyczerpujemy kubełek (limit=2) pierwszą instancją.
    await limiter_before_restart.acquire()
    await limiter_before_restart.acquire()
    assert clock.slept_seconds == []

    # Sama nazwa dostawcy, nowa instancja, ten sam Redis — to jest "restart".
    # Kubełek powinien być nadal pusty (widziany z Redisa), nie świeży.
    limiter_after_restart = RateLimiter(
        provider, 2, redis=get_redis(), clock=clock.time, sleep=clock.sleep
    )
    await limiter_after_restart.acquire()

    assert len(clock.slept_seconds) == 1
