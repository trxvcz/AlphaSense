"""Routing modułu `watchlist` (plan krok 43, etap 8).

Autoryzacja zasobowa wyłącznie przez `Depends(get_owned_watchlist)`
(`WatchlistDep`) — nigdy goły `watchlist_id` z path. Zero SQL w handlerach.

**Watchlista nie jest portfelem.** Odpowiedzi nie niosą ilości, wyceny ani
zwrotu i nie wolno ich tu dołożyć bez zmiany zakresu (CLAUDE.md #3.11).
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Response, status

from app.core.deps import CurrentUserDep, WatchlistDep
from app.db.session import DbSession
from app.modules.watchlist import repository, service
from app.modules.watchlist.schemas import (
    WatchlistCreateIn,
    WatchlistItemIn,
    WatchlistItemOut,
    WatchlistOut,
    WatchlistUpdateIn,
)

router = APIRouter(tags=["watchlists"])


@router.get("/watchlists", response_model=list[WatchlistOut])
async def list_watchlists(user: CurrentUserDep, db: DbSession) -> list[WatchlistOut]:
    rows = await repository.list_watchlists(db, user.id)
    return [
        WatchlistOut(
            id=watchlist.id,
            name=watchlist.name,
            created_at=watchlist.created_at,
            item_count=count,
        )
        for watchlist, count in rows
    ]


@router.post("/watchlists", response_model=WatchlistOut, status_code=status.HTTP_201_CREATED)
async def create_watchlist(
    payload: WatchlistCreateIn, user: CurrentUserDep, db: DbSession
) -> WatchlistOut:
    watchlist = await service.create_watchlist(db, user.id, name=payload.name)
    return WatchlistOut(
        id=watchlist.id,
        name=watchlist.name,
        created_at=watchlist.created_at,
        item_count=0,
    )


@router.patch("/watchlists/{watchlist_id}", response_model=WatchlistOut)
async def update_watchlist(
    payload: WatchlistUpdateIn, watchlist: WatchlistDep, db: DbSession
) -> WatchlistOut:
    updated = await service.rename_watchlist(db, watchlist, name=payload.name)
    items = await repository.list_items(db, updated.id)
    return WatchlistOut(
        id=updated.id,
        name=updated.name,
        created_at=updated.created_at,
        item_count=len(items),
    )


@router.delete("/watchlists/{watchlist_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_watchlist(watchlist: WatchlistDep, db: DbSession) -> Response:
    await repository.delete_watchlist(db, watchlist)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/watchlists/{watchlist_id}/items", response_model=list[WatchlistItemOut])
async def list_items(watchlist: WatchlistDep, db: DbSession) -> list[WatchlistItemOut]:
    rows = await repository.list_items(db, watchlist.id)
    return [
        WatchlistItemOut(
            asset_id=asset.id,
            symbol=asset.symbol,
            name=asset.name,
            market_code=asset.market_code,
            currency=asset.currency,
            note=item.note,
            added_at=item.added_at,
        )
        for item, asset in rows
    ]


@router.put("/watchlists/{watchlist_id}/items/{asset_id}", status_code=status.HTTP_204_NO_CONTENT)
async def add_item(
    asset_id: UUID, payload: WatchlistItemIn, watchlist: WatchlistDep, db: DbSession
) -> Response:
    """`PUT`, nie `POST` — idempotentne: powtórne dodanie tego samego aktywa
    aktualizuje notatkę zamiast zgłaszać błąd (obecność na liście jest
    binarna, więc powtórka nie jest pomyłką)."""
    await service.add_item(db, watchlist, asset_id, note=payload.note)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete(
    "/watchlists/{watchlist_id}/items/{asset_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def remove_item(asset_id: UUID, watchlist: WatchlistDep, db: DbSession) -> Response:
    """204 także wtedy, gdy pozycji nie było — stan końcowy jest ten sam."""
    await repository.remove_item(db, watchlist.id, asset_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
