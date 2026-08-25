"""Kontrakt dostawców kalendarza dywidend (plan krok 47, etap 9).

**Dlaczego znowu osobny protokół, a nie metoda w `DataProvider`/`NewsProvider`.**
Ten sam powód co przy newsach (`news/providers/base.py`): `DataProvider`
opisuje OHLCV/FX/metadane, `NewsProvider` — strumień informacji. Dywidenda
nie jest ani jednym, ani drugim: to zapowiedź zdarzenia w **przyszłości**,
z własnym kluczem naturalnym (`asset_id`, `ex_date`) i własną semantyką
aktualizacji (kwota bywa korygowana, więc świeższa odpowiedź wygrywa).
Dopisanie czwartej metody do `DataProvider` zmusiłoby NBP, Stooq i Binance
do implementowania czegoś, czego nigdy nie zwrócą.

`DividendAnnouncement` jest zamrożoną dataclassą, nie modelem Pydantic —
tak samo jak `PriceBar` i `NewsItem`: to DTO między providerem a ingestią,
nigdy nie przekracza granicy HTTP.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class DividendAnnouncement:
    """Jedno zdarzenie dywidendowe zwrócone przez dostawcę — jeszcze bez
    `asset_id` (tłumaczenie symbolu na aktywo wymaga bazy i należy do
    warstwy ingestii).

    `ex_date` jest jedyną datą wymaganą: bez niej zdarzenia nie da się
    umieścić w kalendarzu ani powiązać z pytaniem „czy zdążę kupić".
    Wpis bez `ex_date` provider ma pominąć, a nie podstawiać `pay_date`
    — to dwie różne daty, potrafiące dzielić kilka tygodni.

    `amount` to kwota **na jedną akcję/jednostkę, brutto, w walucie
    notowania** — nie po podatku i nie w PLN. Podatek u źródła i
    rozliczenie należą do Etapu 21 (CLAUDE.md §22).
    """

    symbol: str
    ex_date: date
    amount: Decimal
    currency: str
    record_date: date | None = None
    pay_date: date | None = None
    declaration_date: date | None = None


@runtime_checkable
class DividendProvider(Protocol):
    """Kontrakt dostawcy kalendarza dywidend.

    Jeden symbol na wywołanie — inaczej niż przy newsach, gdzie istnieje
    tryb zbiorczy. Żaden z darmowych dostawców sprawdzonych w tym kroku
    nie przyjmuje listy symboli dla dywidend, a udawanie trybu zbiorczego
    pętlą ukryłoby przed wołającym realny koszt zapytań (dokładnie ten
    błąd opisuje `BatchNewsProvider` w module newsów).
    """

    name: str

    async def get_dividends(self, symbol: str) -> list[DividendAnnouncement]: ...
