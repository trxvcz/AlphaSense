"""Routing modułu `analytics` — alokacja, koncentracja (plan krok 29, etap 6)
i ranking rynków (`/portfolios/{id}/markets`, krok 30, ADR-102). Ryzyko i
wyniki (`/risk`, `/performance`) to Faza 2 (plan, krok 41 i dalej).

Zero SQL bezpośrednio tutaj (skill `fastapi-modul`) — każdy handler woła
`service.py`. Autoryzacja zasobowa wyłącznie przez `Depends(get_owned_
portfolio)` (`core/deps.py`, skill `izolacja-danych`) — nigdy goły
`portfolio_id` z path bez weryfikacji właściciela. `GET /markets/{code}/
index` (druga część kroku 30) żyje w `modules/marketdata/routes.py` — dotyczy
wyłącznie danych rynkowych globalnych (bez portfela), publiczna trasa jak
`/assets/search` (patrz raport zadania kroku 30).
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
    IndexChangeOut,
    MarketIndexOut,
    MarketRankingItemOut,
    PerformanceOut,
    PerformancePointOut,
)
from app.modules.marketdata.schemas import PricePointOut
from app.modules.portfolio.routes import ValuationRangeParam

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


@router.get("/portfolios/{portfolio_id}/performance", response_model=PerformanceOut)
async def get_performance(
    portfolio: PortfolioDep,
    db: DbSession,
    range_: Annotated[ValuationRangeParam, Query(alias="range")] = ValuationRangeParam.MAX,
) -> PerformanceOut:
    """Zwrot za okres i seria indeksu łańcuchowego ze snapshotów (krok 40,
    ADR-101). Dni zmiany składu zrywają ogniwo — patrz `analytics.returns`.

    `range` reużywa `ValuationRangeParam` z `portfolio.routes` zamiast
    definiować drugi enum o tych samych wartościach: obie trasy schodzą do
    tego samego `repository._range_start`, więc rozjazd list byłby błędem
    typu „422 na `1M`, które gdzie indziej działa". Import trasy z trasy nie
    tworzy cyklu (`portfolio.routes` nie zna `analytics`) i niczego nie
    rejestruje — routery wpina jawnie `app/main.py`.
    """
    result = await service.performance(db, portfolio, range_=range_.value)
    return PerformanceOut(
        range=result.range,
        period_return=result.period_return,
        first_date=result.first_date,
        last_date=result.last_date,
        links=result.links,
        skipped_composition_change=result.skipped_composition_change,
        skipped_zero_base=result.skipped_zero_base,
        points=[
            PerformancePointOut(date=p.date, value_pln=p.value_pln, ret=p.ret, index=p.index)
            for p in result.points
        ],
    )


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


@router.get("/portfolios/{portfolio_id}/markets", response_model=list[MarketRankingItemOut])
async def get_market_ranking(portfolio: PortfolioDep, db: DbSession) -> list[MarketRankingItemOut]:
    """Ranking rynków wg wagi w wartości wycenionego portfela (krok 30,
    ADR-102) — posortowany malejąco po `weight`. `index=null` dla rynku bez
    indeksu referencyjnego (skill `analityka-struktury`)."""
    items = await service.market_ranking(db, portfolio)
    return [
        MarketRankingItemOut(
            market_code=item.market_code,
            market_name=item.market_name,
            weight=item.weight,
            index=(
                MarketIndexOut(
                    asset_id=item.index.asset_id,
                    symbol=item.index.symbol,
                    value=item.index.value,
                    change_1d=(
                        IndexChangeOut(abs=item.index.change_1d.abs, pct=item.index.change_1d.pct)
                        if item.index.change_1d is not None
                        else None
                    ),
                    as_of=item.index.as_of,
                    series_30d=[
                        PricePointOut(date=p.date, close_adj=p.close_adj)
                        for p in item.index.series_30d
                    ],
                )
                if item.index is not None
                else None
            ),
        )
        for item in items
    ]
