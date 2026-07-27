"""Routing modułu `analytics` — alokacja, koncentracja (plan krok 29, etap 6).
Ryzyko i wyniki (`/risk`, `/performance`) to Faza 2 (plan, krok 41 i dalej).

Zero SQL bezpośrednio tutaj (skill `fastapi-modul`) — każdy handler woła
`service.py`. Autoryzacja zasobowa wyłącznie przez `Depends(get_owned_
portfolio)` (`core/deps.py`, skill `izolacja-danych`) — nigdy goły
`portfolio_id` z path bez weryfikacji właściciela.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated

from fastapi import APIRouter, Query

from app.core.deps import PortfolioDep
from app.db.session import DbSession
from app.modules.analytics import service
from app.modules.analytics.schemas import (
    AllocationBucketOut,
    AllocationOut,
    ConcentrationOut,
)

router = APIRouter(tags=["analytics"])


class AllocationDimensionParam(StrEnum):
    """`?by=` w `GET /allocation` — string enum: FastAPI/Pydantic zwraca 422
    na nieznaną wartość zamiast przepuszczać dowolny tekst do
    `service.allocation`/`service._bucket_key` (ten sam wzorzec co
    `ValuationRangeParam` w `modules/portfolio/routes.py`)."""

    CLASS = "class"
    SECTOR = "sector"
    GEO = "geo"
    CURRENCY = "currency"
    MARKET = "market"


@router.get("/portfolios/{portfolio_id}/allocation", response_model=AllocationOut)
async def get_allocation(
    portfolio: PortfolioDep,
    db: DbSession,
    by: Annotated[AllocationDimensionParam, Query()],
) -> AllocationOut:
    """`by` jest wymagany (kontrakt nie definiuje domyślnego wymiaru
    alokacji — decyzja: brak wartości domyślnej, 422 zamiast cichego
    zgadywania, którą alokację użytkownik chciał zobaczyć)."""
    result = await service.allocation(db, portfolio, by=by.value)
    return AllocationOut(
        by=result.by,
        as_of=result.as_of,
        approximate=result.approximate,
        buckets=[
            AllocationBucketOut(key=b.key, value_pln=b.value_pln, weight=b.weight)
            for b in result.buckets
        ],
    )


@router.get("/portfolios/{portfolio_id}/concentration", response_model=ConcentrationOut)
async def get_concentration(portfolio: PortfolioDep, db: DbSession) -> ConcentrationOut:
    result = await service.concentration(db, portfolio)
    return ConcentrationOut(
        top5_share=result.top5_share,
        count=result.count,
        hhi=result.hhi,
        interpretation=result.interpretation,
    )
