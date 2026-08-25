"""Schematy Pydantic modułu `dividends` (plan krok 47, etap 9)."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, field_serializer


class DividendEventOut(BaseModel):
    """Jedno zapowiedziane zdarzenie dywidendowe dla pozycji użytkownika.

    Kwoty jako `string` (CLAUDE.md #3.1). `amount_per_share` jest **brutto,
    w walucie notowania** — bez podatku u źródła i bez przeliczenia na PLN.
    Jedno i drugie należałoby do rozliczenia, czyli do Etapu 21 (§22),
    a przeliczenie „na dziś" kursem NBP byłoby prognozą udającą wycenę:
    kurs właściwy dla wypłaty to kurs z dnia poprzedzającego wypłatę,
    czyli z przyszłości.

    `estimated_gross` = `amount_per_share × quantity`, w tej samej walucie.
    To wprost mnożenie dzisiejszego stanu pozycji przez zapowiedzianą kwotę
    — jeśli użytkownik dokupi albo sprzeda przed ex-datą, liczba się
    zmieni. UI nazywa ją szacunkiem, nie należnością.
    """

    symbol: str
    market_code: str
    ex_date: date
    record_date: date | None
    pay_date: date | None
    declaration_date: date | None
    amount_per_share: Decimal
    currency: str
    quantity: Decimal
    estimated_gross: Decimal
    source: str
    fetched_at: datetime

    @field_serializer("amount_per_share", "quantity", "estimated_gross")
    def _serialize_decimal(self, value: Decimal) -> str:
        return str(value)


class DividendCalendarOut(BaseModel):
    """Kalendarz dywidend portfela wraz z informacją o **zasięgu danych**.

    `assets_without_coverage` i `uncovered_markets` nie są ozdobnikiem —
    to najważniejsza część tej odpowiedzi. Kalendarz pokrywa dziś wyłącznie
    rynki zagraniczne (dostawca: Alpha Vantage), a GPW nie, więc pusty
    ekran dla portfela złożonego z polskich spółek znaczyłby „nie mamy
    danych", a wyglądałby na „nic Cię nie czeka" (CLAUDE.md #3.15, plan
    krok 47: „GPW oznaczone jako ograniczenie").

    Rozróżnienie idzie po **mapowaniu dostawcy**, nie po obecności zdarzeń:
    spółka objęta danymi i niepłacąca dywidendy jest czymś innym niż spółka,
    o którą nie mamy kogo zapytać.
    """

    items: list[DividendEventOut]
    horizon_days: int
    assets_covered: int
    assets_without_coverage: list[str]
    uncovered_markets: list[str]
