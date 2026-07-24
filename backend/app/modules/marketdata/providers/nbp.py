"""`NbpProvider` — jedyne źródło kursów walut (tabela A) i cen złota
(plan krok 21, etap 4, `.claude/skills/data-provider/SKILL.md`).

NBP (Narodowy Bank Polski) publikuje dwa oddzielne, darmowe, bezkluczowe
REST API:

- `GET /api/exchangerates/rates/A/{kod}/{data_od}/{data_do}/` — kursy średnie
  z tabeli A dla waluty `{kod}` (np. `EUR`, `USD`).
- `GET /api/cenyzlota/{data_od}/{data_do}/` — cena 1g złota (Au 999), jedna
  wartość dzienna, bez rozbicia na OHLC.

Oba endpointy zwracają HTTP 404 (nie pustą listę) gdy w całym żądanym
zakresie dat nie ma **żadnego** notowania (typowo: zakres w całości
weekendowy/świąteczny) — to NIE jest błąd (SKILL, reguła 6: „Dzień bez
notowania to nie błąd"), tylko brak danych; traktujemy to identycznie jak
odpowiedź 200 z pustą listą `rates`/`[]`. Pojedyncze brakujące dni w
mieszanym zakresie po prostu nie pojawiają się w zwróconej liście — NBP nie
zwraca dla nich żadnego wpisu, więc nie trzeba niczego specjalnie filtrować.

`NbpProvider` nie zna bazy ani `asset_id` (kontrakt `DataProvider`,
`base.py`) — zwraca surowe DTO, tłumaczeniem/zapisem zajmuje się warstwa
ingestii (`repository.py` w tym samym pakiecie, `upsert_fx_rates`/
`upsert_prices`) w przyszłych krokach (worker EOD, krok 23).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any, Final

import httpx
import structlog

from app.modules.marketdata.providers.base import (
    AssetMetadata,
    Capability,
    FxQuote,
    PriceBar,
)

logger = structlog.get_logger(__name__)

# Symbol złota w naszym słowniku aktywów (rynek `COMMODITY`, patrz
# docs/slownik-rynkow.md) — jedyny symbol, jaki ten provider akceptuje dla
# `get_ohlcv`, bo NBP nie notuje żadnego innego instrumentu OHLCV.
GOLD_SYMBOL: Final[str] = "XAU"

_BASE_URL: Final[str] = "http://api.nbp.pl/api"
# `?format=json` jest obowiązkowe — bez niego NBP zwraca domyślnie XML,
# którego `httpx.Response.json()` nie sparsuje (zweryfikowane na żywo przez
# realne żądanie do api.nbp.pl przy pisaniu tego providera).
_FX_PATH: Final[str] = "/exchangerates/rates/A/{currency}/{start}/{end}/?format=json"
_GOLD_PATH: Final[str] = "/cenyzlota/{start}/{end}/?format=json"
_DEFAULT_TIMEOUT_SECONDS: Final[float] = 10.0


class NbpProvider:
    """`DataProvider` dla NBP: `Capability.FX` (wszystkie waluty tabeli A) i
    `Capability.OHLCV` (wyłącznie złoto, symbol `XAU`).

    Świadomie **bez** `Capability.METADATA`/`SEARCH` — NBP nie ma pojęcia
    o sektorach/krajach/nazwach spółek, to nie jego domena (SKILL,
    tabela „Specyfika źródeł"). `get_metadata` istnieje tylko po to, żeby
    klasa spełniała `Protocol DataProvider` — zawsze zwraca `None`
    (patrz docstring metody, niżej wyjaśniona decyzja).
    """

    name = "nbp"
    supports: set[Capability] = {Capability.FX, Capability.OHLCV}

    def __init__(
        self,
        client: httpx.AsyncClient | None = None,
        *,
        base_url: str = _BASE_URL,
    ) -> None:
        # `client` wstrzykiwalny dla testów/reużycia connection poola przez
        # wołający kod (ingestion); jeśli nic nie podano, provider zarządza
        # własnym klientem i go zamyka (`aclose`). Testy jednostkowe i tak
        # nie muszą wstrzykiwać klienta — `respx` przechwytuje żądania na
        # poziomie transportu niezależnie od instancji `AsyncClient`
        # (patrz `tests/integration/test_auth_oauth.py` dla tego samego
        # wzorca przy Authlib).
        self._client = client if client is not None else httpx.AsyncClient()
        self._owns_client = client is None
        self._base_url = base_url.rstrip("/")

    async def aclose(self) -> None:
        """Zamyka własny klient HTTP, jeśli provider go sam utworzył."""
        if self._owns_client:
            await self._client.aclose()

    async def get_fx(self, currency: str, start: date, end: date) -> list[FxQuote]:
        """Kursy średnie tabeli A dla `currency` w `[start, end]` (włącznie)."""
        code = currency.upper()
        url = self._base_url + _FX_PATH.format(
            currency=code, start=start.isoformat(), end=end.isoformat()
        )
        payload = await self._get_json(url, context={"currency": code, "start": start, "end": end})
        if payload is None:
            return []
        return [
            FxQuote(
                currency=code,
                date=date.fromisoformat(rate["effectiveDate"]),
                rate_pln=_as_decimal(rate["mid"]),
            )
            for rate in payload["rates"]
        ]

    async def get_ohlcv(self, symbol: str, start: date, end: date) -> list[PriceBar]:
        """Cena złota (`symbol == "XAU"`) w `[start, end]` (włącznie).

        NBP publikuje jedną cenę dzienną (nie OHLC) — zgodnie z instrukcją
        kroku 21 mapujemy ją na wszystkie cztery pola
        (`open == high == low == close == close_adj`), `volume=None` (NBP
        nie publikuje wolumenu, to nie jest giełda).

        **Decyzja o innych symbolach niż `XAU`:** rzucamy `ValueError`,
        nie zwracamy pustej listy. Uzasadnienie: pusta lista w tym
        kontrakcie oznacza „poprawne zapytanie, brak notowania w zakresie"
        (święto/weekend, SKILL reguła 6) — to co innego niż „to zapytanie
        jest z definicji błędne dla tego dostawcy". Pomylenie tych dwóch
        przypadków byłoby groźne: błędny wpis w `asset_source_map`
        (np. akcja przypadkiem zmapowana na provider `nbp`) skutkowałby
        cichym brakiem cen bez śladu w logach/`ingestion_runs.error`,
        zamiast czytelnego błędu, który `FallbackChain` złapie, zaloguje
        i (jeśli jest inny dostawca w łańcuchu z tą możliwością) obsłuży
        przez fallback.
        """
        if symbol != GOLD_SYMBOL:
            raise ValueError(
                f"NbpProvider.get_ohlcv obsługuje wyłącznie symbol {GOLD_SYMBOL!r} (złoto), "
                f"otrzymano {symbol!r}"
            )
        url = self._base_url + _GOLD_PATH.format(start=start.isoformat(), end=end.isoformat())
        payload = await self._get_json(url, context={"symbol": symbol, "start": start, "end": end})
        if payload is None:
            return []
        bars: list[PriceBar] = []
        for entry in payload:
            price = _as_decimal(entry["cena"])
            bars.append(
                PriceBar(
                    date=date.fromisoformat(entry["data"]),
                    open=price,
                    high=price,
                    low=price,
                    close=price,
                    close_adj=price,
                    volume=None,
                )
            )
        return bars

    async def get_metadata(self, symbol: str) -> AssetMetadata | None:
        """Zawsze `None` — NBP nie obsługuje `Capability.METADATA`.

        Metoda musi istnieć, żeby klasa spełniała `Protocol DataProvider`
        (`runtime_checkable`), ale nikt nie powinien jej realnie wołać:
        `FallbackChain`/warstwa ingestii filtrują dostawców po `supports`
        przed wywołaniem (`Capability.METADATA not in NbpProvider.supports`).
        Zwracamy `None` zamiast `NotImplementedError`, żeby przypadkowe
        wywołanie (np. z testu, który nie sprawdził `supports`) zachowało
        się zgodnie z deklarowanym typem zwrotu (`AssetMetadata | None`)
        zamiast wywalać wyjątek, którego `Protocol` w ogóle nie deklaruje.
        """
        return None

    async def _get_json(self, url: str, *, context: dict[str, Any]) -> Any | None:
        """GET + parsowanie JSON z `Decimal` zamiast `float` (`parse_float`),
        `None` przy HTTP 404 (brak notowań w całym zakresie — SKILL reguła 6),
        wyjątek dla innych błędów HTTP/sieciowych.
        """
        response = await self._client.get(url, timeout=_DEFAULT_TIMEOUT_SECONDS)
        if response.status_code == httpx.codes.NOT_FOUND:
            logger.info("nbp.no_data_in_range", url=url, **context)
            return None
        response.raise_for_status()
        return response.json(parse_float=Decimal)


def _as_decimal(value: Decimal | float | str) -> Decimal:
    """Konwertuje wartość liczbową z JSON na `Decimal` bez przejścia przez
    `float` (CLAUDE.md #3.1). W praktyce `value` jest już `Decimal`, bo
    `_get_json` woła `response.json(parse_float=Decimal)` — ta funkcja jest
    dodatkową strażniczką (np. dla wywołań spoza `_get_json` w testach,
    które budują payload ręcznie) i nigdy nie robi `Decimal(float)`
    (niebezpieczne — niosłoby błąd reprezentacji binarnej floata), tylko
    `Decimal(str(...))`.
    """
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))
