"""Routing modułu `portfolio` — portfele, pozycje, wycena, historia
wyceny (plan kroki 25-28, etap 5).

Zero SQL bezpośrednio tutaj (skill `fastapi-modul`) — każdy handler woła
`service.py`. Autoryzacja zasobowa wyłącznie przez `Depends(get_owned_
portfolio)`/`Depends(get_owned_holding)` (`core/deps.py`, skill
`izolacja-danych`) — nigdy goły `portfolio_id`/`holding_id` z path bez
weryfikacji właściciela.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated

from fastapi import APIRouter, Query, status

from app.core.deps import CurrentUserDep, HoldingDep, PortfolioDep
from app.db.session import DbSession
from app.modules.portfolio import service
from app.modules.portfolio.schemas import (
    ChangeOut,
    HoldingCreateIn,
    HoldingOut,
    HoldingUpdateIn,
    PortfolioCreateIn,
    PortfolioOut,
    PortfolioUpdateIn,
    SummaryOut,
    ValuationPointOut,
)
from app.modules.portfolio.service import ValuedHolding

router = APIRouter(tags=["portfolio"])


class ValuationRangeParam(StrEnum):
    """`?range=` w `GET /valuations` — string enum: FastAPI zwraca 422 na
    nieznaną wartość zamiast przepuszczać dowolny tekst do
    `service.list_valuations`/`repository.list_valuations`."""

    ONE_MONTH = "1M"
    THREE_MONTHS = "3M"
    ONE_YEAR = "1Y"
    YTD = "YTD"
    MAX = "max"


def _to_holding_out(vh: ValuedHolding) -> HoldingOut:
    return HoldingOut(
        id=vh.holding.id,
        asset_id=vh.holding.asset_id,
        symbol=vh.asset.symbol,
        quantity=vh.holding.quantity,
        avg_cost=vh.holding.avg_cost,
        cost_currency=vh.holding.cost_currency,
        note=vh.holding.note,
        value_pln=vh.value_pln,
        stale=vh.stale,
        as_of=vh.as_of,
        unrealized_pl=vh.unrealized_pl,
        split_suspected=vh.split_suspected,
        price_change_1d=(
            ChangeOut(abs=vh.price_change_1d.abs, pct=vh.price_change_1d.pct)
            if vh.price_change_1d is not None
            else None
        ),
    )


@router.get("/portfolios", response_model=list[PortfolioOut])
async def list_portfolios(user: CurrentUserDep, db: DbSession) -> list[PortfolioOut]:
    """Portfele zalogowanego użytkownika — filtr po `user_id`, nigdy pełna
    tabela (skill `izolacja-danych`)."""
    portfolios = await service.list_portfolios(db, user_id=user.id)
    return [PortfolioOut.model_validate(p) for p in portfolios]


@router.post("/portfolios", response_model=PortfolioOut, status_code=status.HTTP_201_CREATED)
async def create_portfolio(
    body: PortfolioCreateIn, user: CurrentUserDep, db: DbSession
) -> PortfolioOut:
    portfolio = await service.create_portfolio(db, user_id=user.id, name=body.name, type_=body.type)
    return PortfolioOut.model_validate(portfolio)


@router.get("/portfolios/{portfolio_id}", response_model=PortfolioOut)
async def get_portfolio(portfolio: PortfolioDep) -> PortfolioOut:
    return PortfolioOut.model_validate(portfolio)


@router.patch("/portfolios/{portfolio_id}", response_model=PortfolioOut)
async def update_portfolio(
    body: PortfolioUpdateIn, portfolio: PortfolioDep, db: DbSession
) -> PortfolioOut:
    updated = await service.update_portfolio(db, portfolio, name=body.name, type_=body.type)
    return PortfolioOut.model_validate(updated)


@router.delete("/portfolios/{portfolio_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_portfolio(portfolio: PortfolioDep, db: DbSession) -> None:
    """Kaskaduje na `holdings`/`portfolio_valuations` przez `ON DELETE
    CASCADE` w bazie (`models.py`)."""
    await service.delete_portfolio(db, portfolio)


@router.get("/portfolios/{portfolio_id}/holdings", response_model=list[HoldingOut])
async def list_holdings(portfolio: PortfolioDep, db: DbSession) -> list[HoldingOut]:
    """Pozycje portfela **wycenione** na „dziś" (`value_pln`, `stale`,
    ewentualny `unrealized_pl`, `split_suspected` — skill
    `analityka-struktury`)."""
    valued = await service.list_valued_holdings(db, portfolio)
    return [_to_holding_out(vh) for vh in valued]


@router.post(
    "/portfolios/{portfolio_id}/holdings",
    response_model=HoldingOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_holding(
    body: HoldingCreateIn, portfolio: PortfolioDep, db: DbSession
) -> HoldingOut:
    valued = await service.create_holding(
        db,
        portfolio,
        asset_id=body.asset_id,
        quantity=body.quantity,
        avg_cost=body.avg_cost,
        cost_currency=body.cost_currency,
        note=body.note,
    )
    return _to_holding_out(valued)


@router.patch("/holdings/{holding_id}", response_model=HoldingOut)
async def update_holding(body: HoldingUpdateIn, holding: HoldingDep, db: DbSession) -> HoldingOut:
    fields = body.model_fields_set
    update = service.HoldingUpdate(
        # `body.quantity is not None` jest tu zawsze prawdą, gdy "quantity"
        # w `fields` — `HoldingUpdateIn._quantity_no_explicit_null`
        # (schemas.py) odrzuca jawny null 422-ką przed dotarciem tutaj.
        # Sprawdzenie zostaje jako zawężenie typu dla mypy (`HoldingUpdate.
        # quantity` to `Decimal | _Unset`, bez `None`).
        quantity=(
            body.quantity if "quantity" in fields and body.quantity is not None else service.UNSET
        ),
        avg_cost=body.avg_cost if "avg_cost" in fields else service.UNSET,
        cost_currency=body.cost_currency if "cost_currency" in fields else service.UNSET,
        note=body.note if "note" in fields else service.UNSET,
    )
    valued = await service.update_holding(db, holding, update)
    return _to_holding_out(valued)


@router.delete("/holdings/{holding_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_holding(holding: HoldingDep, db: DbSession) -> None:
    """Twardy `DELETE` — `Holding` nie jest historią (ADR-101 „append-only"
    dotyczy wyłącznie `portfolio_valuations`)."""
    await service.delete_holding(db, holding)


@router.get("/portfolios/{portfolio_id}/summary", response_model=SummaryOut)
async def get_summary(portfolio: PortfolioDep, db: DbSession) -> SummaryOut:
    """Wartość live + zmiana d/d i YTD (`change_1d`/`change_ytd` mogą być
    `null`, jeśli worker jeszcze nie zapisał żadnego snapshotu). Bez pola
    `markets` — ranking rynków to krok 29/30 (etap 6)."""
    summary = await service.get_summary(db, portfolio)
    return SummaryOut(
        value_pln=summary.value_pln,
        change_1d=(
            ChangeOut(abs=summary.change_1d.abs, pct=summary.change_1d.pct)
            if summary.change_1d is not None
            else None
        ),
        change_ytd=(
            ChangeOut(abs=summary.change_ytd.abs, pct=summary.change_ytd.pct)
            if summary.change_ytd is not None
            else None
        ),
        as_of=summary.as_of,
        stale_assets=summary.stale_assets,
    )


@router.get("/portfolios/{portfolio_id}/valuations", response_model=list[ValuationPointOut])
async def list_valuations(
    portfolio: PortfolioDep,
    db: DbSession,
    range_: Annotated[ValuationRangeParam, Query(alias="range")] = ValuationRangeParam.MAX,
) -> list[ValuationPointOut]:
    valuations = await service.list_valuations(db, portfolio, range_=range_.value)
    return [ValuationPointOut.model_validate(v) for v in valuations]
