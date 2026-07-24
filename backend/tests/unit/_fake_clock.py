"""Sztuczny zegar do testów `RateLimiter`/`CircuitBreaker` — bez prawdziwego
`sleep`/`time.time()` (docs/konwencje.md, tabela testów: „dostawców").

Nazwa z podkreśleniem na początku: to pomocnik importowany przez testy, nie
plik testowy sam w sobie (nie pasuje do wzorca `test_*.py`, pytest go nie
kolekcjonuje jako testy).

`FakeClock.time` ma sygnaturę `ClockFn` (`() -> float`), `FakeClock.sleep`
ma sygnaturę `SleepFn` (`(float) -> Awaitable[None]`) — obie wstrzykiwane w
konstruktory `RateLimiter`/`CircuitBreaker`. `sleep()` nie czeka naprawdę,
tylko przesuwa zegar do przodu o zadaną liczbę sekund, dzięki czemu testy
„N+1 żądanie czeka X sekund" kończą się natychmiast, deterministycznie.
"""

from __future__ import annotations


class FakeClock:
    def __init__(self, start: float = 1_700_000_000.0) -> None:
        self._now = start
        self.slept_seconds: list[float] = []

    def time(self) -> float:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += seconds

    async def sleep(self, seconds: float) -> None:
        self.slept_seconds.append(seconds)
        if seconds > 0:
            self._now += seconds
