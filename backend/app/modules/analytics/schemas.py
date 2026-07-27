"""Schematy Pydantic modułu `analytics` (request/response) — plan krok 29,
etap 6: alokacja wg wymiaru i koncentracja (HHI).

Kwoty/ułamki (`Decimal` w modelu) serializowane do stringa (`format(v, "f")`,
skill `fastapi-modul`) — nigdy `float`. Kwantyzacja (miejsca po przecinku)
jest już zrobiona w `service.py` zanim dane trafią tutaj — schematy tylko
serializują, nie zaokrąglają (skill `fastapi-modul`: „backend liczy z pełną
precyzją i zaokrągla wyłącznie na końcu, jawnie").
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from pydantic import BaseModel, field_serializer


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
