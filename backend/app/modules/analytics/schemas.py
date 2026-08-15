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
from datetime import date as date_
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


class BenchmarkPointOut(BaseModel):
    """Punkt serii benchmarku wyrównany do daty snapshotu portfela.

    `as_of` bywa wcześniejsze niż `date` (weekend, święto giełdowe) — bez
    tego „benchmark stoi w miejscu" wygląda tak samo jak „giełda była
    zamknięta" (CLAUDE.md #3.15)."""

    date: date
    as_of: date_
    index: Decimal

    @field_serializer("index")
    def _ser(self, v: Decimal) -> str:
        return _ser_decimal(v)


class BenchmarkOut(BaseModel):
    """Seria porównawcza w `GET /performance?benchmark=` (krok 42).

    `approximate=true` + `note` dla WIG20: liczone z ETF-a `ETFBW20TR`, bo
    sam indeks nie ma dostępnego źródła historii (decyzja 8 planu etapu 8).
    UI ma to pokazać, nie ukryć.

    `unavailable_reason` niepuste ⇒ `points` puste. Powód jest po polsku
    i wprost do wyświetlenia — wykres bez linii i bez wyjaśnienia wygląda
    jak awaria.
    """

    key: str
    symbol: str
    label: str
    currency: str
    approximate: bool
    note: str | None
    unavailable_reason: str | None
    points: list[BenchmarkPointOut]


class PerformancePointOut(BaseModel):
    """Punkt serii wyników (`GET /performance`, plan krok 40).

    `ret=null` znaczy „zwrotu za ten dzień NIE ZNAMY" — pierwszy punkt serii
    albo dzień zmiany składu (ADR-101). To nie to samo co `"0"` i UI nie
    może tych przypadków zlewać (CLAUDE.md #3.15).
    """

    date: date
    value_pln: Decimal
    ret: Decimal | None
    index: Decimal

    @field_serializer("value_pln", "index")
    def _ser(self, v: Decimal) -> str:
        return _ser_decimal(v)

    @field_serializer("ret")
    def _ser_optional(self, v: Decimal | None) -> str | None:
        return None if v is None else _ser_decimal(v)


class PerformanceOut(BaseModel):
    """Wyjście `GET /portfolios/{portfolio_id}/performance?range=`.

    `period_return=null` dla serii bez ani jednego ogniwa (portfel bez
    historii) — znowu: brak zwrotu, nie zwrot zerowy.

    `links`/`skipped_*` są częścią odpowiedzi, nie diagnostyką: zwrot za rok
    policzony z 40 ogniw wygląda tak samo jak z 250, a znaczy co innego
    (decyzja 6 planu etapu 8).
    """

    range: str
    period_return: Decimal | None
    first_date: date | None
    last_date: date | None
    links: int
    skipped_composition_change: int
    skipped_zero_base: int
    points: list[PerformancePointOut]
    benchmark: BenchmarkOut | None

    @field_serializer("period_return")
    def _ser_optional(self, v: Decimal | None) -> str | None:
        return None if v is None else _ser_decimal(v)
