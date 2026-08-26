"""`AlphaVantageDividendsProvider` — kalendarz dywidend (plan krok 47, etap 9),
REST `https://www.alphavantage.co/query?function=DIVIDENDS`.

**Plan mówił „Finnhub dla zagranicy" — Finnhub tego nie oddaje.**
`GET /stock/dividend?symbol=AAPL` zwraca na darmowym planie
`403 {"error":"You don't have access to this resource."}` (sprawdzone
2026-08-23 realnym kluczem produkcyjnym, ten sam wynik co `/news-sentiment`
w kroku 46). Dostawca zmieniony na Alpha Vantage, u którego funkcja
`DIVIDENDS` jest w darmowym planie i oddaje komplet czterech dat plus kwotę
(sprawdzone tym samym dniem: AAPL, ex-data 2026-08-10, wypłata 2026-08-13).
Zakres kroku bez zmian — zmienia się tylko źródło, bo zaplanowane okazało
się niedostępne.

**GPW nie jest pokryta i to nie jest usterka do naprawienia w tym kroku.**
`DIVIDENDS` dla `PKN.WAR` zwraca `{"symbol": "PKN.WAR", "data": []}` —
pustą listę, nie błąd, czyli odpowiedź nie do odróżnienia od „spółka nie
płaci". Dokładnie dlatego kalendarz **nigdy** nie wnioskuje o braku
dywidendy z pustej odpowiedzi: warstwa wyżej rozstrzyga pokrycie po
mapowaniu `asset_source_map` (dostawca `alphavantage`), a aktywo bez
mapowania jest raportowane jako **nieobjęte**, a nie jako „bez dywidend"
(CLAUDE.md #3.15, plan krok 47: „GPW oznaczone jako ograniczenie").

**Budżet zapytań jest tu twardym ograniczeniem projektowym.** Darmowy plan
to 25 zapytań na dobę, dzielone z jobem sentymentu z kroku 46
(12 przebiegów/dobę). Ten dostawca nie umie trybu zbiorczego — jeden symbol
= jedno zapytanie — więc limitowanie liczby symboli na przebieg należy do
joba (`worker/jobs/ingest_dividends.py`), nie do tego pliku.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx
import structlog

from app.core.config import get_settings
from app.core.errors import ProviderUnavailableError
from app.modules.dividends.providers.base import DividendAnnouncement
from app.modules.marketdata.providers.http_client import get_with_backoff
from app.modules.marketdata.providers.rate_limiter import RateLimiter

logger = structlog.get_logger(__name__)

_BASE_URL = "https://www.alphavantage.co/query"
_REQUEST_TIMEOUT = 15.0
# Pojemność kolumny `dividend_events.amount` = NUMERIC(20,8).
_MAX_AMOUNT = Decimal("1e12")


def _parse_date(raw: Any) -> date | None:
    """`"2026-08-10"` → `date`, wszystko inne → `None`.

    Alpha Vantage wstawia w nieznane daty literał `"None"` (string, nie
    `null`) — bez tej funkcji `date.fromisoformat` rzucałby wyjątkiem na
    normalnym, poprawnym wpisie o jeszcze nieustalonym dniu wypłaty.
    """
    if not isinstance(raw, str):
        return None
    try:
        return date.fromisoformat(raw.strip())
    except ValueError:
        return None


class AlphaVantageDividendsProvider:
    """Kalendarz dywidend per symbol. `name` jest zapisywane w
    `dividend_events.source`, więc identyfikuje dostawcę, nie funkcję API."""

    name = "alphavantage_dividends"

    def __init__(
        self,
        client: httpx.AsyncClient,
        *,
        limiter: RateLimiter | None = None,
        api_key: str | None = None,
    ) -> None:
        self._client = client
        self._limiter = limiter or RateLimiter(self.name, get_settings().rate_limit_alphavantage)
        # `None` = czytaj leniwie przy wywołaniu, tak samo jak pozostali
        # dostawcy Alpha Vantage/Finnhub — żeby testy mogły nadpisać
        # `Settings` bez rekonstrukcji providera.
        self._api_key = api_key

    async def get_dividends(self, symbol: str) -> list[DividendAnnouncement]:
        api_key = (
            self._api_key if self._api_key is not None else get_settings().alphavantage_api_key
        )
        if not api_key:
            raise ProviderUnavailableError(
                "Brak ALPHAVANTAGE_API_KEY — dostawca dywidend niedostępny.",
                details={"provider": self.name},
            )

        response = await get_with_backoff(
            self._client,
            _BASE_URL,
            params={"function": "DIVIDENDS", "symbol": symbol, "apikey": api_key},
            limiter=self._limiter,
            request_timeout=_REQUEST_TIMEOUT,
        )
        rows = self._data_or_raise(response.json(), symbol)
        return [item for raw in rows if (item := self._parse_entry(raw, symbol)) is not None]

    def _data_or_raise(self, payload: Any, symbol: str) -> list[Any]:
        """Wyciąga `data` albo rzuca `ProviderUnavailableError`.

        Ta sama pułapka co przy `NEWS_SENTIMENT` (krok 46): Alpha Vantage
        **nie sygnalizuje błędów kodem HTTP** — wyczerpany limit dobowy, zły
        klucz i nieznana funkcja wracają jako `200 OK` z kluczem
        `Information`/`Note`/`Error Message`. Bez tej kontroli
        `payload.get("data", [])` zamieniłoby każdą z tych awarii w „ta
        spółka nie płaci dywidendy" — czyli w fałszywy fakt na ekranie
        użytkownika, a nie w awarię, którą widzi bezpiecznik.
        """
        if not isinstance(payload, dict):
            raise ProviderUnavailableError(
                "Alpha Vantage zwrócił odpowiedź w nieoczekiwanym kształcie.",
                details={"provider": self.name, "symbol": symbol},
            )
        for key in ("Information", "Note", "Error Message"):
            message = payload.get(key)
            if message:
                raise ProviderUnavailableError(
                    f"Alpha Vantage odmówił odpowiedzi: {message}",
                    details={"provider": self.name, "symbol": symbol},
                )
        rows = payload.get("data")
        if not isinstance(rows, list):
            raise ProviderUnavailableError(
                "Alpha Vantage nie zwrócił listy `data`.",
                details={"provider": self.name, "symbol": symbol},
            )
        return rows

    def _parse_entry(self, raw: Any, symbol: str) -> DividendAnnouncement | None:
        """Jeden wiersz `data` → `DividendAnnouncement`, albo `None`.

        Waluta **nie przychodzi od dostawcy** — `DIVIDENDS` jej nie podaje.
        Uzupełnia ją warstwa ingestii z `assets.currency` (waluta notowania
        aktywa), bo tylko ona wie, o które aktywo chodzi. Tutaj zostaje
        pusty string, którego job nie zapisze do bazy bez podmiany —
        zgadywanie „pewnie USD" wpisałoby walutę do kolumny, której jedynym
        zadaniem jest mówić prawdę o kwocie.
        """
        if not isinstance(raw, dict):
            return None
        ex_date = _parse_date(raw.get("ex_dividend_date"))
        if ex_date is None:
            return None
        try:
            amount = Decimal(str(raw.get("amount")).strip())
        except (InvalidOperation, AttributeError):
            return None
        # `NaN`/`Infinity` przechodzą przez konstruktor `Decimal` bez błędu,
        # a `Decimal("NaN") <= 0` rzuca `InvalidOperation` — dlatego kontrola
        # skończoności musi iść **przed** porównaniem, nie po nim. Górny limit
        # to pojemność kolumny `NUMERIC(20,8)` (12 cyfr przed przecinkiem):
        # większa kwota i tak wywaliłaby zapis do bazy, więc lepiej odrzucić
        # ją jako artefakt danych tutaj, bez przewracania całego symbolu.
        # Dywidenda ujemna albo zerowa nie jest zdarzeniem, tylko artefaktem
        # danych — a zerowa kwota w kalendarzu wygląda jak zapowiedź wypłaty
        # niczego.
        if not amount.is_finite() or amount <= 0 or amount >= _MAX_AMOUNT:
            return None

        return DividendAnnouncement(
            symbol=symbol,
            ex_date=ex_date,
            amount=amount,
            currency="",
            record_date=_parse_date(raw.get("record_date")),
            pay_date=_parse_date(raw.get("payment_date")),
            declaration_date=_parse_date(raw.get("declaration_date")),
        )
