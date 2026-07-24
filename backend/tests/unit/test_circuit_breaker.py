"""Testy `CircuitBreaker` (`app.modules.marketdata.providers.circuit_breaker`).

Stan w Redisie (jak `RateLimiter`, patrz uzasadnienie w
`test_rate_limiter.py`), zegar wstrzyknięty (`FakeClock`) — `reset_timeout`
„upływa" przez `clock.advance(...)`, nigdy przez prawdziwe czekanie.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator

import pytest

from app.core.cache import get_redis
from app.modules.marketdata.providers.circuit_breaker import CircuitBreaker
from tests.unit._fake_clock import FakeClock


def _make_breaker(
    *, failure_threshold: int = 3, reset_timeout: int = 60, clock: FakeClock | None = None
) -> tuple[CircuitBreaker, FakeClock]:
    provider = f"test-breaker-{uuid.uuid4().hex}"
    clock = clock or FakeClock()
    breaker = CircuitBreaker(
        provider,
        failure_threshold=failure_threshold,
        reset_timeout=reset_timeout,
        redis=get_redis(),
        clock=clock.time,
    )
    return breaker, clock


@pytest.fixture(autouse=True)
async def _cleanup_circuit_breaker_keys() -> AsyncGenerator[None, None]:
    yield
    async for key in get_redis().scan_iter("circuit_breaker:test-breaker-*"):
        await get_redis().delete(key)


async def test_circuit_is_closed_by_default() -> None:
    breaker, _ = _make_breaker()
    assert await breaker.is_open() is False


async def test_circuit_stays_closed_below_failure_threshold() -> None:
    breaker, _ = _make_breaker(failure_threshold=3)

    await breaker.record_failure()
    await breaker.record_failure()

    assert await breaker.is_open() is False


async def test_circuit_opens_after_failure_threshold_consecutive_failures() -> None:
    breaker, _ = _make_breaker(failure_threshold=3)

    for _ in range(3):
        await breaker.record_failure()

    assert await breaker.is_open() is True


async def test_success_resets_failure_count_before_threshold() -> None:
    """Sukces między błędami zeruje licznik — obwód nie otwiera się po
    kolejnych, nieciągłych błędach poniżej progu."""
    breaker, _ = _make_breaker(failure_threshold=3)

    await breaker.record_failure()
    await breaker.record_failure()
    await breaker.record_success()
    await breaker.record_failure()
    await breaker.record_failure()

    assert await breaker.is_open() is False


async def test_no_trial_allowed_before_reset_timeout_elapses() -> None:
    breaker, clock = _make_breaker(failure_threshold=1, reset_timeout=60)

    await breaker.record_failure()
    assert await breaker.is_open() is True

    clock.advance(59)
    assert await breaker.allow_trial() is False


async def test_trial_allowed_after_reset_timeout_elapses() -> None:
    breaker, clock = _make_breaker(failure_threshold=1, reset_timeout=60)

    await breaker.record_failure()
    clock.advance(60)

    assert await breaker.allow_trial() is True


async def test_only_one_trial_allowed_per_window() -> None:
    """Drugi wołający w tym samym oknie (np. inny worker) nie dostaje
    kolejnego próbnego zapytania, dopóki pierwsze się nie rozstrzygnie."""
    breaker, clock = _make_breaker(failure_threshold=1, reset_timeout=60)

    await breaker.record_failure()
    clock.advance(60)

    assert await breaker.allow_trial() is True
    assert await breaker.allow_trial() is False


async def test_successful_trial_closes_circuit() -> None:
    breaker, clock = _make_breaker(failure_threshold=1, reset_timeout=60)

    await breaker.record_failure()
    clock.advance(60)
    assert await breaker.allow_trial() is True

    await breaker.record_success()

    assert await breaker.is_open() is False


async def test_failed_trial_keeps_circuit_open_and_restarts_timeout() -> None:
    breaker, clock = _make_breaker(failure_threshold=1, reset_timeout=60)

    await breaker.record_failure()
    clock.advance(60)
    assert await breaker.allow_trial() is True

    await breaker.record_failure()

    assert await breaker.is_open() is True
    # zegar zrestartowany przy porażce próbnego zapytania — zaraz po nim
    # kolejna próba wciąż nie jest dozwolona.
    assert await breaker.allow_trial() is False

    clock.advance(60)
    assert await breaker.allow_trial() is True


async def test_state_is_visible_across_independent_instances() -> None:
    """Stan musi żyć w Redisie, nie w pamięci procesu (docstring klasy) —
    dwie niezależne instancje z tą samą nazwą dostawcy symulują tu proces
    przed i po restarcie workera. Bez tego test breaker mógłby "działać"
    tylko dlatego, że jedna instancja trzyma stan lokalnie.
    """
    provider = f"test-breaker-restart-{uuid.uuid4().hex}"
    clock = FakeClock()
    breaker_before_restart = CircuitBreaker(
        provider, failure_threshold=1, reset_timeout=60, redis=get_redis(), clock=clock.time
    )

    await breaker_before_restart.record_failure()
    assert await breaker_before_restart.is_open() is True

    # Sama nazwa dostawcy, nowa instancja, ten sam Redis — to jest "restart".
    breaker_after_restart = CircuitBreaker(
        provider, failure_threshold=1, reset_timeout=60, redis=get_redis(), clock=clock.time
    )
    assert await breaker_after_restart.is_open() is True

    clock.advance(60)
    assert await breaker_after_restart.allow_trial() is True
    await breaker_after_restart.record_success()

    # Zamknięcie przez "nową" instancję musi być widoczne z powrotem
    # w "starej" — obie czytają ten sam klucz Redis, nie stan lokalny.
    assert await breaker_before_restart.is_open() is False
