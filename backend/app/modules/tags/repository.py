"""Zapis/odczyt tagów użytkownika i powiązań z aktywami (plan krok 43).

Każde zapytanie w tym module jest **zawężone do właściciela** — albo przez
`Tag.user_id`, albo przez `JOIN tags` przy `asset_tags`. `assets` jest
słownikiem globalnym, więc gdyby powiązania czytać bez tego zawężenia,
użytkownik zobaczyłby cudze etykiety na tych samych spółkach.
"""

from __future__ import annotations

from uuid import UUID

import structlog
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.tags.models import AssetTag, Tag

logger = structlog.get_logger(__name__)


async def list_tags(db: AsyncSession, user_id: UUID) -> list[Tag]:
    """Tagi użytkownika, alfabetycznie — tak są pokazywane w filtrze."""
    result = await db.execute(select(Tag).where(Tag.user_id == user_id).order_by(Tag.name))
    return list(result.scalars().all())


async def get_tag_by_name(db: AsyncSession, user_id: UUID, name: str) -> Tag | None:
    """Tag po nazwie — do wykrycia duplikatu PRZED naruszeniem `UNIQUE`.

    Sprawdzenie w aplikacji zamiast łapania `IntegrityError`, bo tylko tutaj
    da się oddać sensowny komunikat po polsku; ograniczenie w bazie zostaje
    jako ostatnia linia obrony przy równoległych żądaniach.
    """
    tag: Tag | None = await db.scalar(select(Tag).where(Tag.user_id == user_id, Tag.name == name))
    return tag


async def create_tag(db: AsyncSession, user_id: UUID, *, name: str, color: str | None) -> Tag:
    tag = Tag(user_id=user_id, name=name, color=color)
    db.add(tag)
    await db.commit()
    await db.refresh(tag)
    logger.info("tags.created", tag_id=str(tag.id))
    return tag


async def update_tag(db: AsyncSession, tag: Tag, *, name: str | None, color: str | None) -> Tag:
    """Aktualizacja częściowa. `color=None` w wywołaniu znaczy „nie zmieniaj",
    a nie „skasuj kolor" — rozróżnienie robi warstwa serwisu na podstawie
    tego, które pola faktycznie przyszły w żądaniu (`model_fields_set`)."""
    if name is not None:
        tag.name = name
    if color is not None:
        tag.color = color
    await db.commit()
    await db.refresh(tag)
    return tag


async def clear_tag_color(db: AsyncSession, tag: Tag) -> Tag:
    tag.color = None
    await db.commit()
    await db.refresh(tag)
    return tag


async def delete_tag(db: AsyncSession, tag: Tag) -> None:
    """Usuwa tag; powiązania w `asset_tags` znikają kaskadą z bazy."""
    await db.delete(tag)
    await db.commit()
    logger.info("tags.deleted", tag_id=str(tag.id))


async def attach_asset(db: AsyncSession, tag_id: UUID, asset_id: UUID) -> bool:
    """Wiąże tag z aktywem. `True`, gdy powiązanie było nowe.

    `ON CONFLICT DO NOTHING` — otagowanie już otagowanego aktywa to nie
    błąd, tylko brak zmiany (idempotencja, CLAUDE.md #3.9).
    """
    stmt = (
        insert(AssetTag)
        .values(tag_id=tag_id, asset_id=asset_id)
        .on_conflict_do_nothing(index_elements=[AssetTag.tag_id, AssetTag.asset_id])
        # `.returning()` zamiast `rowcount`: przy `DO NOTHING` wiersz wraca
        # tylko wtedy, gdy faktycznie powstał — ten sam wzorzec co
        # `news/repository.py`, i jedyny, który typuje się bez `cast`.
        .returning(AssetTag.asset_id)
    )
    inserted = await db.scalar(stmt)
    await db.commit()
    return inserted is not None


async def detach_asset(db: AsyncSession, tag_id: UUID, asset_id: UUID) -> bool:
    """Zdejmuje powiązanie. `False`, gdy go nie było."""
    removed = await db.scalar(
        delete(AssetTag)
        .where(AssetTag.tag_id == tag_id, AssetTag.asset_id == asset_id)
        .returning(AssetTag.asset_id)
    )
    await db.commit()
    return removed is not None


async def list_asset_ids(db: AsyncSession, tag_id: UUID) -> list[UUID]:
    result = await db.execute(
        select(AssetTag.asset_id).where(AssetTag.tag_id == tag_id).order_by(AssetTag.created_at)
    )
    return list(result.scalars().all())


async def asset_ids_for_tag_names(db: AsyncSession, user_id: UUID, names: list[str]) -> set[UUID]:
    """Aktywa użytkownika oznaczone **którymkolwiek** z podanych tagów.

    Semantyka **OR (suma), nie AND (przecięcie)** — `?tags=dywidendowe,REIT`
    czyta się jako „pokaż mi jedne i drugie", a przecięcie dla większości par
    tagów dałoby pustą listę i wyglądało jak awaria filtra. Filtr AND, gdyby
    kiedyś był potrzebny, wymaga osobnego parametru, a nie zmiany znaczenia
    tego (złamałoby to kontrakt).

    Nieznana nazwa tagu po prostu nic nie wnosi do sumy — nie jest błędem
    (użytkownik mógł usunąć tag w innej karcie przeglądarki).
    """
    if not names:
        return set()
    result = await db.execute(
        select(AssetTag.asset_id)
        .join(Tag, Tag.id == AssetTag.tag_id)
        .where(Tag.user_id == user_id, Tag.name.in_(names))
    )
    return set(result.scalars().all())


async def tags_by_asset(
    db: AsyncSession, user_id: UUID, asset_ids: list[UUID]
) -> dict[UUID, list[Tag]]:
    """Mapa `asset_id → tagi użytkownika`, jednym zapytaniem.

    Jedno zapytanie na całą listę pozycji, nie jedno na pozycję: widok
    struktury pokazuje etykiety przy każdym wierszu, a zapytanie per wiersz
    dałoby N+1 na ekranie, który i tak liczy już alokację.
    """
    if not asset_ids:
        return {}
    result = await db.execute(
        select(AssetTag.asset_id, Tag)
        .join(Tag, Tag.id == AssetTag.tag_id)
        .where(Tag.user_id == user_id, AssetTag.asset_id.in_(asset_ids))
        .order_by(Tag.name)
    )
    mapping: dict[UUID, list[Tag]] = {}
    for asset_id, tag in result.all():
        mapping.setdefault(asset_id, []).append(tag)
    return mapping
