"""Logika tagów (plan krok 43) — cienka warstwa nad repozytorium.

Jedyna nietrywialna decyzja żyje tutaj, a nie w trasie: **duplikat nazwy to
`ConflictError` (409), nie `IntegrityError` z bazy**. Ograniczenie
`uq_tags_user_name` zostaje jako ostatnia linia obrony przy równoległych
żądaniach, ale zwykły przypadek („już mam taki tag") ma dostać zdanie po
polsku, a nie 500.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, NotFoundError
from app.modules.marketdata.models import Asset
from app.modules.tags import repository
from app.modules.tags.models import AssetTag, Tag


async def list_tags_with_counts(db: AsyncSession, user_id: UUID) -> list[tuple[Tag, int]]:
    """Tagi użytkownika z liczbą otagowanych aktywów.

    `LEFT JOIN` + `COUNT`, jednym zapytaniem — tag bez aktywów ma się
    pokazać z zerem, a nie zniknąć z listy (`INNER JOIN` by go zgubił,
    i byłby to najgorszy moment: tuż po utworzeniu).
    """
    result = await db.execute(
        select(Tag, func.count(AssetTag.asset_id))
        .outerjoin(AssetTag, AssetTag.tag_id == Tag.id)
        .where(Tag.user_id == user_id)
        .group_by(Tag.id)
        .order_by(Tag.name)
    )
    return [(tag, count) for tag, count in result.all()]


async def create_tag(db: AsyncSession, user_id: UUID, *, name: str, color: str | None) -> Tag:
    if await repository.get_tag_by_name(db, user_id, name) is not None:
        raise ConflictError(f"Tag o nazwie {name!r} już istnieje.")
    return await repository.create_tag(db, user_id, name=name, color=color)


async def rename_tag(
    db: AsyncSession, tag: Tag, *, name: str | None, color: str | None, clear_color: bool
) -> Tag:
    if name is not None and name != tag.name:
        if await repository.get_tag_by_name(db, tag.user_id, name) is not None:
            raise ConflictError(f"Tag o nazwie {name!r} już istnieje.")
    if clear_color:
        await repository.clear_tag_color(db, tag)
    return await repository.update_tag(db, tag, name=name, color=color)


async def attach_asset(db: AsyncSession, tag: Tag, asset_id: UUID) -> bool:
    """Wiąże tag z aktywem po sprawdzeniu, że aktywo w ogóle istnieje.

    Bez tego sprawdzenia nieistniejące `asset_id` wywaliłoby się na FK jako
    500. `assets` jest słownikiem globalnym, więc nie ma tu czego zawężać do
    właściciela — chroniony zasób to tag, zweryfikowany przez `get_owned_tag`.
    """
    if await db.scalar(select(Asset.id).where(Asset.id == asset_id)) is None:
        raise NotFoundError("Nie znaleziono aktywa")
    return await repository.attach_asset(db, tag.id, asset_id)


async def list_tagged_assets(db: AsyncSession, tag: Tag) -> list[Asset]:
    result = await db.execute(
        select(Asset)
        .join(AssetTag, AssetTag.asset_id == Asset.id)
        .where(AssetTag.tag_id == tag.id)
        .order_by(Asset.symbol)
    )
    return list(result.scalars().all())
