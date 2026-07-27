"""Schematy Pydantic modułu `analytics` (request/response) — plan krok 29,
etap 6: alokacja wg wymiaru i koncentracja (HHI). Rozszerzone w kroku 30
(ADR-102) o ranking rynków (`GET /portfolios/{portfolio_id}/markets`).

Kwoty/ułamki (`Decimal` w modelu) serializowane do stringa (`format(v, "f")`,
skill `fastapi-modul`) — nigdy `float`. Kwantyzacja (miejsca po przecinku)
jest już zrobiona w `service.py` zanim dane trafią tutaj — schematy tylko
serializują, nie zaokrąglają (skill `fastapi-modul`: „backend liczy z pełną
precyzją i zaokrągla wyłącznie na końcu, jawnie").

`MarketIndexOut.series_30d` reużywa `marketdata.schemas.PricePointOut` —
ten sam kształt punktu danych co `GET /markets/{code}/index`, nie
duplikujemy go (jesteśmy w `analytics`, ale importujemy z `marketdata` —
oba to moduły backendu w tym samym repo, nie ma tu granicy „cudzego"
prywatnego szczegółu: `PricePointOut` jest publicznym schematem wyjścia).
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from pydantic import BaseModel, field_serializer

from app.modules.marketdata.schemas import PricePointOut


def _ser_decimal(v: Decimal) -> str:
    return format(v, "f")


class AllocationBucketOut(BaseModel):
    """Jeden koszyk alokacji (np. jedna klasa aktywów albo jeden sektor)."""

    key: str
    value_pln: Decimal
    weight: Decimal

    @field_serializer("value_pln", "weight")
    def _ser(self, v: Decimal) -> str:
        return _ser_decimal(v)


class AllocationOut(BaseModel):
    """Wyjście `GET /portfolios/{portfolio_id}/allocation?by=`.

    `approximate=true` tylko dla `by=sector`/`by=geo`, gdy w wycenionych
    pozycjach jest choć jeden ETF (sektor/geografia ETF-a to przybliżenie —
    skill `analityka-struktury`). Suma `weight` po `buckets` jest zawsze
    dokładnie `1` (poza przypadkiem pustych `buckets`, gdzie nie ma czego
    sumować) — patrz `service._distribute_weights`.
    """

    by: str
    as_of: date
    approximate: bool
    buckets: list[AllocationBucketOut]


class ConcentrationOut(BaseModel):
    """Wyjście `GET /portfolios/{portfolio_id}/concentration`."""

    top5_share: Decimal
    count: int
    hhi: Decimal
    interpretation: str

    @field_serializer("top5_share", "hhi")
    def _ser(self, v: Decimal) -> str:
        return _ser_decimal(v)


class IndexChangeOut(BaseModel):
    """Zmiana d/d wartości indeksu referencyjnego — liczona wprost z dwóch
    najnowszych wierszy `prices` (nie ze snapshotów portfela, w
    przeciwieństwie do `ChangeOut` w `modules/portfolio/schemas.py`, stąd
    osobny typ zamiast reużycia tamtego)."""

    abs: Decimal
    pct: Decimal

    @field_serializer("abs", "pct")
    def _ser(self, v: Decimal) -> str:
        return _ser_decimal(v)


class MarketIndexOut(BaseModel):
    """Indeks referencyjny jednego rynku w rankingu — `null` na poziomie
    `MarketRankingItemOut.index`, gdy rynek nie ma `index_asset_id` (skill
    `analityka-struktury`: „Jeśli rynek nie ma indeksu — pokaż samą wagę,
    bez pustego wykresu"). `change_1d` jest `null`, gdy w `prices` jest
    najwyżej jedno notowanie (nie ma z czym porównać) — ten sam brzegowy
    przypadek co `ChangeOut`/`Change` gdzie indziej w API."""

    asset_id: uuid.UUID
    symbol: str
    value: Decimal
    change_1d: IndexChangeOut | None
    as_of: date
    series_30d: list[PricePointOut]

    @field_serializer("value")
    def _ser_value(self, v: Decimal) -> str:
        return _ser_decimal(v)


class MarketRankingItemOut(BaseModel):
    """Jeden wiersz `GET /portfolios/{portfolio_id}/markets` — rynek
    posortowany malejąco po `weight` (waga w wartości wycenionego portfela,
    4 miejsca, ta sama precyzja co `AllocationBucketOut.weight`)."""

    market_code: str
    market_name: str
    weight: Decimal
    index: MarketIndexOut | None

    @field_serializer("weight")
    def _ser_weight(self, v: Decimal) -> str:
        return _ser_decimal(v)
