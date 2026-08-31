"""Schematy Pydantic modułu `portfolio` (request/response) — plan kroki
25-28, etap 5: CRUD portfeli/pozycji, wycena PLN, summary, historia
wyceny, heurystyka splitu.

Kwoty (`Decimal` w modelu, `condecimal`/`Field` do walidacji) serializowane
do stringa (`format(v, "f")`, skill `fastapi-modul`) — nigdy `float`.
Pola opcjonalne wyceny (`value_pln`, `unrealized_pl`) mogą być `None`
(pozycja bez ceny/kursu albo bez podanego `avg_cost`) — serializer
przepuszcza `None` bez zmian, nigdy nie podstawia `"0"` (CLAUDE.md,
skill `analityka-struktury`: „nie licz jako zero").
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_serializer, model_validator


def _ser_decimal(v: Decimal) -> str:
    return format(v, "f")


def _ser_optional_decimal(v: Decimal | None) -> str | None:
    return format(v, "f") if v is not None else None


class PortfolioCreateIn(BaseModel):
    """Wejście `POST /portfolios`."""

    name: str = Field(min_length=1, max_length=200)
    type: str = Field(min_length=1, max_length=50)


class PortfolioUpdateIn(BaseModel):
    """Wejście `PATCH /portfolios/{portfolio_id}` — oba pola opcjonalne.

    Jawny `null` traktowany tak samo jak pole pominięte (bez zmiany) —
    `name`/`type` to kolumny `NOT NULL`, więc „wyczyść" nie ma tu sensu
    domenowego (w przeciwieństwie do np. `Holding.note`).
    """

    name: str | None = Field(default=None, min_length=1, max_length=200)
    type: str | None = Field(default=None, min_length=1, max_length=50)

    @model_validator(mode="after")
    def _no_explicit_null(self) -> PortfolioUpdateIn:
        """`name`/`type` to kolumny `NOT NULL` — pole pominięte w JSON = bez
        zmian, ale jawny `null` jest błędem klienta (422), nie cichym
        pominięciem: inaczej żądanie zwraca 200 mimo że wysłana wartość
        została zignorowana, co maskuje błąd frontendu (np. formularz
        wysyłający `null` zamiast realnej wartości — code-review etapu 5)."""
        for name in ("name", "type"):
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError(f"{name} nie może być null (pomiń pole, by nie zmieniać)")
        return self


class PortfolioOut(BaseModel):
    """Wyjście reprezentujące portfel."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    type: str
    holdings_version: int
    created_at: datetime


class HoldingCreateIn(BaseModel):
    """Wejście `POST /portfolios/{portfolio_id}/holdings`.

    `avg_cost`/`cost_currency` opcjonalne razem (CLAUDE.md #1: serce
    produktu to struktura, nie księgowość) — jeśli `avg_cost` podany,
    `cost_currency` jest wymagany (odzwierciedla CHECK
    `avg_cost_needs_currency` w `Holding`, ale weryfikowane już tu, żeby
    dać czytelny 422 zamiast polegać wyłącznie na błędzie bazy).
    """

    asset_id: uuid.UUID
    quantity: Decimal = Field(ge=0)
    avg_cost: Decimal | None = Field(default=None, gt=0)
    cost_currency: str | None = Field(default=None, pattern=r"^[A-Za-z]{3}$")
    note: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def _avg_cost_needs_currency(self) -> HoldingCreateIn:
        if self.avg_cost is not None and self.cost_currency is None:
            raise ValueError("avg_cost wymaga podania cost_currency")
        return self


class HoldingUpdateIn(BaseModel):
    """Wejście `PATCH /holdings/{holding_id}` — wszystkie pola opcjonalne.

    Semantyka PATCH: pole pominięte w JSON = bez zmian; `avg_cost`/
    `cost_currency`/`note` jawnie ustawione na `null` = wyczyszczone
    (kolumny nullable). `quantity` jawnie `null` to błąd klienta (422,
    `_quantity_no_explicit_null` niżej) — kolumna `NOT NULL`, „wyczyść
    ilość" nie ma sensu domenowego, więc lepiej odrzucić niż ciche
    pominięcie (code-review etapu 5). Spójność `avg_cost`/`cost_currency`
    po scaleniu z istniejącą pozycją
    weryfikuje `service.update_holding` (potrzebuje finalnego stanu, nie
    tylko tego, co przyszło w tym jednym żądaniu).
    """

    quantity: Decimal | None = Field(default=None, ge=0)
    avg_cost: Decimal | None = Field(default=None, gt=0)
    cost_currency: str | None = Field(default=None, pattern=r"^[A-Za-z]{3}$")
    note: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def _quantity_no_explicit_null(self) -> HoldingUpdateIn:
        """`quantity` to kolumna `NOT NULL` — pole pominięte w JSON = bez
        zmian, ale jawny `null` jest błędem klienta (422), nie cichym
        pominięciem (ten sam powód co `PortfolioUpdateIn._no_explicit_null`,
        code-review etapu 5)."""
        if "quantity" in self.model_fields_set and self.quantity is None:
            raise ValueError("quantity nie może być null (pomiń pole, by nie zmieniać ilości)")
        return self


class ChangeOut(BaseModel):
    """Zmiana wartości (d/d albo YTD) — `abs`olutna i procentowa. Używana
    zarówno dla zmiany wartości portfela (`SummaryOut`), jak i zmiany ceny
    instrumentu d/d per pozycja (`HoldingOut.price_change_1d`) — to samo
    kształt danych, inny mianownik."""

    abs: Decimal
    pct: Decimal

    @field_serializer("abs", "pct")
    def _ser(self, v: Decimal) -> str:
        return _ser_decimal(v)


class HoldingOut(BaseModel):
    """Wyjście reprezentujące wycenioną pozycję — `GET/POST .../holdings`,
    `PATCH /holdings/{holding_id}`. Budowane w `routes.py` z
    `service.ValuedHolding` (nie ORM bezpośrednio — `symbol` pochodzi z
    joinowanego `Asset`, nie z `Holding`), stąd brak `from_attributes`.
    """

    id: uuid.UUID
    asset_id: uuid.UUID
    symbol: str
    quantity: Decimal
    avg_cost: Decimal | None
    cost_currency: str | None
    note: str | None
    value_pln: Decimal | None
    stale: bool
    as_of: date | None
    unrealized_pl: Decimal | None
    split_suspected: bool
    price_change_1d: ChangeOut | None
    """Zmiana ceny instrumentu d/d (`close_adj` dziś vs poprzednie
    notowanie) — NIE zmiana `value_pln` portfela ani `unrealized_pl`.
    `null`, gdy jest mniej niż dwa notowania w historii (świeżo dodane
    aktywo, przygotowanie pod plan krok 32 „top ruchy dnia")."""

    @field_serializer("quantity")
    def _ser_quantity(self, v: Decimal) -> str:
        return _ser_decimal(v)

    @field_serializer("avg_cost", "value_pln", "unrealized_pl")
    def _ser_optional(self, v: Decimal | None) -> str | None:
        return _ser_optional_decimal(v)


class SummaryOut(BaseModel):
    """Wyjście `GET /portfolios/{portfolio_id}/summary`.

    Bez pola `markets` (ranking rynków) — świadomie, to krok 29/30
    (etap 6), poza zakresem tego kroku (patrz `docs/api-kontrakt.md`).
    """

    value_pln: Decimal
    change_1d: ChangeOut | None
    change_ytd: ChangeOut | None
    as_of: date
    stale_assets: int

    @field_serializer("value_pln")
    def _ser_value(self, v: Decimal) -> str:
        return _ser_decimal(v)


class ValuationPointOut(BaseModel):
    """Jeden punkt serii `GET /portfolios/{portfolio_id}/valuations` —
    mapowany bezpośrednio z `PortfolioValuation` (`from_attributes`)."""

    model_config = ConfigDict(from_attributes=True)

    date: date
    value_pln: Decimal
    composition_change: bool

    @field_serializer("value_pln")
    def _ser_value(self, v: Decimal) -> str:
        return _ser_decimal(v)


class HoldingsImportIn(BaseModel):
    """Wejście `POST /portfolios/{portfolio_id}/holdings/import` (plan krok 48).

    Zawartość pliku leci jako pole JSON, nie `multipart/form-data`: upload
    pliku wymagałby `python-multipart`, czyli nowej zależności backendu
    (CLAUDE.md §10 — zależność wymaga decyzji użytkownika), a przeglądarka
    i tak czyta plik po stronie klienta.

    `dry_run` zwraca ten sam raport, **niczego nie zapisując**. Domyślnie
    `false`, ale frontend woła najpierw z `true`: import scala ilości z
    istniejącymi pozycjami, a tego nie da się cofnąć jednym przyciskiem.
    """

    content: str = Field(min_length=1)
    dry_run: bool = False


class ImportRowOut(BaseModel):
    """Los pojedynczego wiersza pliku. `line` to numer linii w pliku (od 1),
    żeby użytkownik znalazł wpis w edytorze."""

    line: int
    symbol: str
    status: str
    """`created` / `merged` / `skipped`."""
    message: str | None


class HoldingsImportReportOut(BaseModel):
    """Wyjście importu — raport zamiast listy pozycji.

    Import częściowo się udaje z założenia (nieznany symbol nie unieważnia
    reszty pliku), więc odpowiedź musi umieć powiedzieć „12 dodanych, 3
    pominięte i dlaczego". Lista wycenionych pozycji jest do pobrania
    zwykłym `GET .../holdings`.
    """

    dry_run: bool
    created: int
    merged: int
    skipped: int
    rows: list[ImportRowOut]
