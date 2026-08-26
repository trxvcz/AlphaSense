"""Testy list obserwowanych (plan krok 43, etap 8).

Poza zwykłym CRUD-em i izolacją ten plik pilnuje jednej granicy zakresu:
**watchlista to nie drugi portfel** (CLAUDE.md #3.11). Pozycja listy nie ma
ilości ani wyceny, więc `WatchlistItemOut` nie może zacząć ich oddawać
„przy okazji" — test sprawdza kształt odpowiedzi wprost.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator

import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.marketdata.models import Asset
from app.modules.watchlist.models import Watchlist, WatchlistItem

EMAIL_A = "wl-a@example.com"
EMAIL_B = "wl-b@example.com"
PASSWORD = "correct-password-1"


async def _register_and_login(client: AsyncClient, email: str) -> str:
    r = await client.post("/api/auth/register", json={"email": email, "password": PASSWORD})
    assert r.status_code == 201, r.text
    r = await client.post("/api/auth/login", json={"email": email, "password": PASSWORD})
    assert r.status_code == 200, r.text
    token: str = r.json()["access_token"]
    return token


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def watched_asset(db_session: AsyncSession) -> AsyncGenerator[Asset, None]:
    suffix = uuid.uuid4().hex[:8]
    asset = Asset(
        symbol=f"WL{suffix}",
        name=f"Watch asset {suffix}",
        asset_class="equity",
        market_code="GPW",
        currency="PLN",
    )
    db_session.add(asset)
    await db_session.commit()
    await db_session.refresh(asset)

    yield asset

    await db_session.execute(delete(WatchlistItem).where(WatchlistItem.asset_id == asset.id))
    await db_session.execute(delete(Asset).where(Asset.id == asset.id))
    await db_session.commit()


@pytest_asyncio.fixture(autouse=True)
async def _clean_watchlists(db_session: AsyncSession) -> AsyncGenerator[None, None]:
    yield
    await db_session.execute(delete(Watchlist))
    await db_session.commit()


async def _create_watchlist(client: AsyncClient, token: str, name: str) -> str:
    resp = await client.post("/api/watchlists", json={"name": name}, headers=_auth(token))
    assert resp.status_code == 201, resp.text
    watchlist_id: str = resp.json()["id"]
    return watchlist_id


async def test_crud_listy_od_utworzenia_do_usuniecia(
    client: AsyncClient, watched_asset: Asset
) -> None:
    token = await _register_and_login(client, EMAIL_A)
    watchlist_id = await _create_watchlist(client, token, "Do obserwacji")

    listed = await client.get("/api/watchlists", headers=_auth(token))
    assert listed.status_code == 200
    # Świeżo założona, pusta lista ma się pokazać z zerem, a nie zniknąć.
    assert [(w["name"], w["item_count"]) for w in listed.json()] == [("Do obserwacji", 0)]

    added = await client.put(
        f"/api/watchlists/{watchlist_id}/items/{watched_asset.id}",
        json={"note": "czekam na wyniki"},
        headers=_auth(token),
    )
    assert added.status_code == 204

    items = await client.get(f"/api/watchlists/{watchlist_id}/items", headers=_auth(token))
    assert items.status_code == 200
    item = items.json()[0]
    assert item["symbol"] == watched_asset.symbol
    assert item["note"] == "czekam na wyniki"
    # Granica zakresu: lista obserwowanych nie jest portfelem.
    assert "value_pln" not in item
    assert "quantity" not in item

    # `PUT` jest idempotentny i AKTUALIZUJE notatkę — obecność na liście jest
    # binarna, więc powtórka nie jest pomyłką.
    again = await client.put(
        f"/api/watchlists/{watchlist_id}/items/{watched_asset.id}",
        json={"note": "po wynikach"},
        headers=_auth(token),
    )
    assert again.status_code == 204
    items = await client.get(f"/api/watchlists/{watchlist_id}/items", headers=_auth(token))
    assert len(items.json()) == 1
    assert items.json()[0]["note"] == "po wynikach"

    renamed = await client.patch(
        f"/api/watchlists/{watchlist_id}", json={"name": "Obserwowane"}, headers=_auth(token)
    )
    assert renamed.status_code == 200
    assert renamed.json()["name"] == "Obserwowane"
    assert renamed.json()["item_count"] == 1

    removed = await client.delete(
        f"/api/watchlists/{watchlist_id}/items/{watched_asset.id}", headers=_auth(token)
    )
    assert removed.status_code == 204
    # 204 także wtedy, gdy pozycji już nie było.
    removed_again = await client.delete(
        f"/api/watchlists/{watchlist_id}/items/{watched_asset.id}", headers=_auth(token)
    )
    assert removed_again.status_code == 204

    deleted = await client.delete(f"/api/watchlists/{watchlist_id}", headers=_auth(token))
    assert deleted.status_code == 204
    assert (await client.get("/api/watchlists", headers=_auth(token))).json() == []


async def test_duplikat_nazwy_listy_to_409(client: AsyncClient) -> None:
    token = await _register_and_login(client, EMAIL_A)
    await _create_watchlist(client, token, "Do obserwacji")

    resp = await client.post(
        "/api/watchlists", json={"name": "Do obserwacji"}, headers=_auth(token)
    )

    assert resp.status_code == 409, resp.text


async def test_cudza_lista_to_404_a_nie_403(client: AsyncClient) -> None:
    token_a = await _register_and_login(client, EMAIL_A)
    token_b = await _register_and_login(client, EMAIL_B)
    watchlist_id = await _create_watchlist(client, token_a, "Do obserwacji")

    resp = await client.get(f"/api/watchlists/{watchlist_id}/items", headers=_auth(token_b))

    assert resp.status_code == 404, resp.text


async def test_ta_sama_nazwa_listy_u_dwoch_uzytkownikow(client: AsyncClient) -> None:
    token_a = await _register_and_login(client, EMAIL_A)
    token_b = await _register_and_login(client, EMAIL_B)

    id_a = await _create_watchlist(client, token_a, "Do obserwacji")
    id_b = await _create_watchlist(client, token_b, "Do obserwacji")

    assert id_a != id_b
    assert len((await client.get("/api/watchlists", headers=_auth(token_b))).json()) == 1


async def test_nieistniejace_aktywo_na_liscie_to_404_a_nie_500(client: AsyncClient) -> None:
    token = await _register_and_login(client, EMAIL_A)
    watchlist_id = await _create_watchlist(client, token, "Do obserwacji")

    resp = await client.put(
        f"/api/watchlists/{watchlist_id}/items/{uuid.uuid4()}",
        json={"note": None},
        headers=_auth(token),
    )

    assert resp.status_code == 404, resp.text
