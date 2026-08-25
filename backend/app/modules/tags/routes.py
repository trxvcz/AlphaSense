"""Routing modułu `tags` (plan krok 43, etap 8).

Chronionym zasobem jest **tag**, nie aktywo: `assets` to słownik globalny,
a to `tags.user_id` niesie własność. Stąd trasy wiążące mają kształt
`/tags/{tag_id}/assets/{asset_id}`, a nie `/assets/{asset_id}/tags/...` —
przy tym drugim ID w ścieżce, które trzeba zweryfikować, byłoby drugie
w kolejności i łatwo byłoby o nim zapomnieć (skill `izolacja-danych`).

Zero SQL bezpośrednio tutaj — handlery wołają `service.py`/`repository.py`.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Response, status

from app.core.deps import CurrentUserDep, TagDep
from app.db.session import DbSession
from app.modules.tags import repository, service
from app.modules.tags.schemas import TagAssetOut, TagCreateIn, TagOut, TagUpdateIn

router = APIRouter(tags=["tags"])


@router.get("/tags", response_model=list[TagOut])
async def list_tags(user: CurrentUserDep, db: DbSession) -> list[TagOut]:
    """Tagi zalogowanego użytkownika, alfabetycznie, z licznikiem aktywów."""
    rows = await service.list_tags_with_counts(db, user.id)
    return [
        TagOut(
            id=tag.id,
            name=tag.name,
            color=tag.color,
            created_at=tag.created_at,
            asset_count=count,
        )
        for tag, count in rows
    ]


@router.post("/tags", response_model=TagOut, status_code=status.HTTP_201_CREATED)
async def create_tag(payload: TagCreateIn, user: CurrentUserDep, db: DbSession) -> TagOut:
    tag = await service.create_tag(db, user.id, name=payload.name, color=payload.color)
    return TagOut(
        id=tag.id,
        name=tag.name,
        color=tag.color,
        created_at=tag.created_at,
        asset_count=0,
    )


@router.patch("/tags/{tag_id}", response_model=TagOut)
async def update_tag(payload: TagUpdateIn, tag: TagDep, db: DbSession) -> TagOut:
    """Aktualizacja częściowa.

    Jawny `"color": null` kasuje kolor, pominięcie pola go zostawia —
    rozróżnia to `model_fields_set`. Bez tego rozróżnienia zmiana samej
    nazwy kasowałaby kolor przy okazji.
    """
    clear_color = "color" in payload.model_fields_set and payload.color is None
    updated = await service.rename_tag(
        db, tag, name=payload.name, color=payload.color, clear_color=clear_color
    )
    asset_ids = await repository.list_asset_ids(db, updated.id)
    return TagOut(
        id=updated.id,
        name=updated.name,
        color=updated.color,
        created_at=updated.created_at,
        asset_count=len(asset_ids),
    )


@router.delete("/tags/{tag_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_tag(tag: TagDep, db: DbSession) -> Response:
    """Usuwa tag wraz z powiązaniami (kaskada w bazie). Aktywa zostają —
    tag to etykieta, nie właściciel aktywa."""
    await repository.delete_tag(db, tag)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/tags/{tag_id}/assets", response_model=list[TagAssetOut])
async def list_tag_assets(tag: TagDep, db: DbSession) -> list[TagAssetOut]:
    assets = await service.list_tagged_assets(db, tag)
    return [TagAssetOut.model_validate(asset) for asset in assets]


@router.put("/tags/{tag_id}/assets/{asset_id}", status_code=status.HTTP_204_NO_CONTENT)
async def attach_asset(asset_id: UUID, tag: TagDep, db: DbSession) -> Response:
    """`PUT`, nie `POST` — operacja jest idempotentna (`ON CONFLICT DO
    NOTHING`), a dwukrotne otagowanie tego samego aktywa nie jest błędem."""
    await service.attach_asset(db, tag, asset_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("/tags/{tag_id}/assets/{asset_id}", status_code=status.HTTP_204_NO_CONTENT)
async def detach_asset(asset_id: UUID, tag: TagDep, db: DbSession) -> Response:
    """204 także wtedy, gdy powiązania nie było — stan końcowy jest ten sam,
    a 404 kazałoby klientowi rozróżniać przypadki, które go nie obchodzą."""
    await repository.detach_asset(db, tag.id, asset_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
