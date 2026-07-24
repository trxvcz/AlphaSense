"""Typy zegara/uśpienia do wstrzykiwania w `RateLimiter`/`CircuitBreaker`.

`RateLimiter` i `CircuitBreaker` mierzą czas (okna limitu, timeout obwodu) —
w testach jednostkowych (`tests/unit/test_rate_limiter.py`,
`test_circuit_breaker.py`) nie chcemy ani prawdziwego `asyncio.sleep`
(testy trwałyby sekundy/minuty), ani zależności od rzeczywistego zegara
(niedeterminizm). Zamiast tego obie klasy przyjmują `clock`/`sleep` jako
parametry konstruktora z wartościami domyślnymi zdefiniowanymi tutaj —
testy podstawiają sztuczny zegar (`FakeClock` w `tests/unit/_fake_clock.py`)
i sztuczne „uśpienie", które tylko przesuwa ten zegar do przodu, bez
faktycznego czekania.

Świadomie bez `freezegun`: `RateLimiter` liczy okno w skrypcie Lua
wykonywanym po stronie serwera Redis — `freezegun` łata czas w procesie
Pythona, nie w Redisie, więc i tak nie pomogłoby przy logice liczonej
atomowo w Lua. Jawne wstrzykiwanie `ClockFn`/`SleepFn` działa jednakowo
dla obu klas i nie dodaje nowej zależności.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable

ClockFn = Callable[[], float]
"""Zwraca „teraz" jako sekundy (float), zgodnie z semantyką `time.time()`."""

SleepFn = Callable[[float], Awaitable[None]]
"""Usypia (asynchronicznie) na `n` sekund, zgodnie z semantyką `asyncio.sleep`."""


def default_clock() -> float:
    """Prawdziwy zegar — wartość domyślna poza testami."""
    return time.time()


async def default_sleep(seconds: float) -> None:
    """Prawdziwe uśpienie — wartość domyślna poza testami."""
    if seconds > 0:
        await asyncio.sleep(seconds)
