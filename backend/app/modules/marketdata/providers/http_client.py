"""Wspólne narzędzia HTTP dla dostawców opartych o surowe REST/CSV
(Stooq, Finnhub, Binance — `yfinance`/NBP nie korzystają z tego modułu:
`yfinance` to biblioteka bez surowego HTTP po naszej stronie, NBP to
osobny krok/plik równoległy).

**Dlaczego osobny helper zamiast kopiować pętlę retry w każdym providerze:**
zasada #1 zadania („RateLimiter per dostawca... przy HTTP 429 backoff
wykładniczy z jitterem") dotyczy **reaktywnej** obsługi 429 zwróconego przez
zdalne API — to coś innego niż `Guarded` (`guarded.py`), który **proaktywnie**
throttluje nasze wywołania *przed* wysłaniem żądania (token bucket, zero
wiedzy o odpowiedzi). Oba mechanizmy używają tego samego `RateLimiter`
(ta sama nazwa dostawcy → ten sam klucz Redis), ale różnych metod:
`Guarded` woła `acquire()`, provider (przez ten moduł) woła `backoff()` po
realnym 429. Bez tego pliku każdy z trzech providerów HTTP musiałby
duplikować identyczną pętlę `while True: ... if 429: backoff() ...`.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Protocol

import httpx


class SupportsBackoff(Protocol):
    """Wąski interfejs, jakiego potrzebuje `get_with_backoff` — tylko
    `backoff()`, nie cały `RateLimiter` (`rate_limiter.py`). Produkcyjnie
    zawsze przekazywany jest prawdziwy `RateLimiter` (strukturalnie pasuje
    bez żadnego dziedziczenia), w testach wystarczy prosty fake bez Redisa.
    """

    async def backoff(self, attempt: int) -> None: ...


async def get_with_backoff(
    client: httpx.AsyncClient,
    url: str,
    *,
    params: dict[str, str],
    limiter: SupportsBackoff,
    request_timeout: float,
) -> httpx.Response:
    """`GET` z retry na HTTP 429 przez `limiter.backoff(attempt)` (wykładniczy
    odstęp z jitterem, `RateLimiter.backoff` rzuca `ProviderUnavailableError`
    po wyczerpaniu prób — patrz `rate_limiter.py`). Każdy inny status
    niż 2xx/429 leci przez `raise_for_status()` (`httpx.HTTPStatusError`),
    złapie go `Guarded`/`FallbackChain` jak każdy inny wyjątek providera.

    Parametr nazwany `request_timeout`, nie `timeout` — `ruff` (reguła
    `ASYNC109`) ostrzega przed parametrem `timeout` w sygnaturze funkcji
    `async def`, bo to zwykle znak, że funkcja powinna zamiast tego użyć
    `asyncio.timeout()` po stronie wołającego; tu `timeout` to zwyczajny
    parametr przekazywany dalej do `httpx` (timeout pojedynczego żądania
    HTTP), nie własny mechanizm anulowania — inna nazwa wystarczy, żeby to
    odróżnić bez tłumienia reguły przez `noqa`.
    """
    attempt = 0
    while True:
        response = await client.get(url, params=params, timeout=request_timeout)
        if response.status_code == 429:
            await limiter.backoff(attempt)
            attempt += 1
            continue
        response.raise_for_status()
        return response


def decimal_or_none(raw: str | float | int | None) -> Decimal | None:
    """Parsuje komórkę CSV/JSON na `Decimal`, `None` dla pustej/brakującej
    wartości. Nigdy `float` w wyniku (CLAUDE.md #3.1) — `str(raw)` zanim
    trafi do `Decimal`, żeby ewentualny `float` z JSON-a (Finnhub, Binance
    zwracają część pól jako liczby, nie stringi) nie wniósł błędu
    zaokrąglenia binarnego wprost do `Decimal`.
    """
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    try:
        return Decimal(text)
    except InvalidOperation:
        return None


def int_or_none(raw: str | float | int | None) -> int | None:
    """Jak `decimal_or_none`, ale dla wolumenu (`int`). Przechodzi przez
    `Decimal` po drodze, żeby wartości typu `"185340.0"` (spotykane w CSV)
    nie wywaliły `int(str)` z `ValueError`.
    """
    value = decimal_or_none(raw)
    return int(value) if value is not None else None
