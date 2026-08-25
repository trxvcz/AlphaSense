"""Logika list obserwowanych (plan krok 43).

Ta sama decyzja co przy tagach: duplikat nazwy to `ConflictError` (409)
z komunikatem po polsku, a nie `IntegrityError` z bazy przerobiony na 500.
Ograniczenie `uq_watchlists_user_name` zostaje jako ostatnia linia obrony.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, NotFoundError
from app.modules.marketdata.models import Asset
from app.modules.watchlist import repository
from app.modules.watchlist.models import Watchlist


async def create_watchlist(db: AsyncSession, user_id: UUID, *, name: str) -> Watchlist:
    if await repository.get_by_name(db, user_id, name) is not None:
        raise ConflictError(f"Lista o nazwie {name!r} już istnieje.")
    return await repository.create_watchlist(db, user_id, name=name)


async def rename_watchlist(db: AsyncSession, watchlist: Watchlist, *, name: str) -> Watchlist:
    if name != watchlist.name:
        if await repository.get_by_name(db, watchlist.user_id, name) is not None:
            raise ConflictError(f"Lista o nazwie {name!r} już istnieje.")
    return await repository.rename_watchlist(db, watchlist, name=name)


async def add_item(
    db: AsyncSession, watchlist: Watchlist, asset_id: UUID, *, note: str | None
) -> bool:
    """Dodaje aktywo po sprawdzeniu, że istnieje w słowniku.

    Bez tego nieistniejące `asset_id` wywaliłoby się na FK jako 500.
    Chroniony zasób to lista (zweryfikowana przez `get_owned_watchlist`),
    a `assets` jest globalne, więc nie ma tu czego zawężać do właściciela.
    """
    if await db.scalar(select(Asset.id).where(Asset.id == asset_id)) is None:
        raise NotFoundError("Nie znaleziono aktywa")
    return await repository.add_item(db, watchlist.id, asset_id, note=note)
