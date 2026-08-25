"""Zapis/odczyt list obserwowanych (plan krok 43).

Wszystkie odczyty zawężone do właściciela — przez `Watchlist.user_id` albo
przez `watchlist_id` już zweryfikowany zależnością `get_owned_watchlist`.
"""

from __future__ import annotations

from uuid import UUID

import structlog
from sqlalchemy import Boolean, delete, func, literal_column, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.marketdata.models import Asset
from app.modules.watchlist.models import Watchlist, WatchlistItem

logger = structlog.get_logger(__name__)


async def list_watchlists(db: AsyncSession, user_id: UUID) -> list[tuple[Watchlist, int]]:
    """Listy użytkownika z licznikiem pozycji, alfabetycznie.

    `LEFT JOIN` + `COUNT`: świeżo założona, pusta lista ma się pokazać
    z zerem, a nie zniknąć.
    """
    result = await db.execute(
        select(Watchlist, func.count(WatchlistItem.asset_id))
        .outerjoin(WatchlistItem, WatchlistItem.watchlist_id == Watchlist.id)
        .where(Watchlist.user_id == user_id)
        .group_by(Watchlist.id)
        .order_by(Watchlist.name)
    )
    return [(watchlist, count) for watchlist, count in result.all()]


async def get_by_name(db: AsyncSession, user_id: UUID, name: str) -> Watchlist | None:
    watchlist: Watchlist | None = await db.scalar(
        select(Watchlist).where(Watchlist.user_id == user_id, Watchlist.name == name)
    )
    return watchlist


async def create_watchlist(db: AsyncSession, user_id: UUID, *, name: str) -> Watchlist:
    watchlist = Watchlist(user_id=user_id, name=name)
    db.add(watchlist)
    await db.commit()
    await db.refresh(watchlist)
    logger.info("watchlists.created", watchlist_id=str(watchlist.id))
    return watchlist


async def rename_watchlist(db: AsyncSession, watchlist: Watchlist, *, name: str) -> Watchlist:
    watchlist.name = name
    await db.commit()
    await db.refresh(watchlist)
    return watchlist


async def delete_watchlist(db: AsyncSession, watchlist: Watchlist) -> None:
    """Usuwa listę; pozycje znikają kaskadą. Aktywa zostają nietknięte."""
    await db.delete(watchlist)
    await db.commit()
    logger.info("watchlists.deleted", watchlist_id=str(watchlist.id))


async def list_items(db: AsyncSession, watchlist_id: UUID) -> list[tuple[WatchlistItem, Asset]]:
    """Pozycje listy wraz z danymi słownikowymi aktywa.

    Jednym `JOIN`em, nie zapytaniem per pozycja — lista obserwowanych bez
    nazw i rynków byłaby kolumną tickerów, a N+1 na dwudziestu pozycjach to
    dwadzieścia zapytań na jeden ekran.
    """
    result = await db.execute(
        select(WatchlistItem, Asset)
        .join(Asset, Asset.id == WatchlistItem.asset_id)
        .where(WatchlistItem.watchlist_id == watchlist_id)
        .order_by(Asset.symbol)
    )
    return [(item, asset) for item, asset in result.all()]


async def add_item(
    db: AsyncSession, watchlist_id: UUID, asset_id: UUID, *, note: str | None
) -> bool:
    """Dodaje aktywo do listy. `True`, gdy pozycja była nowa.

    `ON CONFLICT DO UPDATE` na `note` — dodanie już obecnego aktywa
    z nową notatką ma notatkę zaktualizować, a nie zgłosić błąd. Sama
    obecność na liście jest binarna, więc powtórka nie jest pomyłką.
    """
    stmt = insert(WatchlistItem).values(watchlist_id=watchlist_id, asset_id=asset_id, note=note)
    # `xmax = 0` odróżnia INSERT od UPDATE w `ON CONFLICT DO UPDATE` (ten
    # sam wzorzec i to samo uzasadnienie co w `dividends/repository.py`) —
    # bez tego nie da się powiedzieć, czy pozycja jest nowa, czy tylko
    # dostała nową notatkę.
    upsert = stmt.on_conflict_do_update(
        index_elements=[WatchlistItem.watchlist_id, WatchlistItem.asset_id],
        set_={"note": stmt.excluded.note},
    ).returning(literal_column("xmax = 0", Boolean))
    is_new: bool | None = await db.scalar(upsert)
    await db.commit()
    return bool(is_new)


async def remove_item(db: AsyncSession, watchlist_id: UUID, asset_id: UUID) -> bool:
    removed = await db.scalar(
        delete(WatchlistItem)
        .where(WatchlistItem.watchlist_id == watchlist_id, WatchlistItem.asset_id == asset_id)
        .returning(WatchlistItem.asset_id)
    )
    await db.commit()
    return removed is not None
