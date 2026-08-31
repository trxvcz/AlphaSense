"""Testy CRUD tagów i filtra `?tags=` w alokacji (plan krok 43, etap 8).

Osią jest to, czego nie widać w samych trasach: **tag należy do
użytkownika, a `assets` jest słownikiem globalnym**. Ten sam ticker
otagowany przez dwie osoby to dwie niezależne etykiety — gdyby odczyt
powiązań pominął zawężenie po `tags.user_id`, użytkownik A zobaczyłby,
że ktoś inny oznaczył PKN jako „do sprzedania".
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from decimal import Decimal

import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.marketdata.models import Asset, FxRate, Price
from app.modules.portfolio.models import Holding
from app.modules.portfolio.service import today
from app.modules.tags.models import AssetTag, Tag

EMAIL_A = "tags-a@example.com"
EMAIL_B = "tags-b@example.com"
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
async def tag_assets(db_session: AsyncSession) -> AsyncGenerator[list[Asset], None]:
    """Dwa aktywa na dwóch różnych rynkach — żeby filtr po tagu dało się
    odróżnić od braku filtru w rozbiciu `by=market`."""
    suffix = uuid.uuid4().hex[:8]
    assets = [
        Asset(
            symbol=f"TAG{index}{suffix}",
            name=f"Tag asset {index} {suffix}",
            asset_class="equity",
            market_code=market,
            currency=currency,
        )
        for index, (market, currency) in enumerate(((("GPW"), "PLN"), ("US", "USD")), start=1)
    ]
    db_session.add_all(assets)
    await db_session.commit()
    for asset in assets:
        await db_session.refresh(asset)

    d = today()
    db_session.add_all(
        [
            Price(asset_id=asset.id, date=d, close=Decimal("100"), close_adj=Decimal("100"))
            for asset in assets
        ]
    )
    # Pozycja w USD bez kursu NBP nie da się wycenić, więc znika z alokacji
    # i rozbicie `by=market` ma tylko GPW. Na czystej bazie CI takiego kursu
    # nie ma — wstawiamy go idempotentnie i **nie kasujemy** przy sprzątaniu,
    # bo może pochodzić z prawdziwego seeda/ingestii.
    await db_session.execute(
        pg_insert(FxRate.__table__)
        .values(currency="USD", date=d, rate_pln=Decimal("4"))
        .on_conflict_do_nothing(index_elements=["currency", "date"])
    )
    await db_session.commit()

    yield assets

    asset_ids = [asset.id for asset in assets]
    await db_session.execute(delete(AssetTag).where(AssetTag.asset_id.in_(asset_ids)))
    await db_session.execute(delete(Holding).where(Holding.asset_id.in_(asset_ids)))
    await db_session.execute(delete(Price).where(Price.asset_id.in_(asset_ids)))
    await db_session.execute(delete(Asset).where(Asset.id.in_(asset_ids)))
    await db_session.commit()


@pytest_asyncio.fixture(autouse=True)
async def _clean_tags(db_session: AsyncSession) -> AsyncGenerator[None, None]:
    yield
    await db_session.execute(delete(Tag))
    await db_session.commit()


async def _create_tag(client: AsyncClient, token: str, name: str, color: str | None = None) -> str:
    payload: dict[str, object] = {"name": name}
    if color is not None:
        payload["color"] = color
    resp = await client.post("/api/tags", json=payload, headers=_auth(token))
    assert resp.status_code == 201, resp.text
    tag_id: str = resp.json()["id"]
    return tag_id


async def test_crud_tagu_od_utworzenia_do_usuniecia(
    client: AsyncClient, tag_assets: list[Asset]
) -> None:
    token = await _register_and_login(client, EMAIL_A)
    tag_id = await _create_tag(client, token, "dywidendowe", "#00ff00")

    listed = await client.get("/api/tags", headers=_auth(token))
    assert listed.status_code == 200
    assert [(t["name"], t["asset_count"]) for t in listed.json()] == [("dywidendowe", 0)]

    attach = await client.put(f"/api/tags/{tag_id}/assets/{tag_assets[0].id}", headers=_auth(token))
    assert attach.status_code == 204
    # `PUT` jest idempotentny — drugie wywołanie to nie błąd, tylko ten sam stan.
    again = await client.put(f"/api/tags/{tag_id}/assets/{tag_assets[0].id}", headers=_auth(token))
    assert again.status_code == 204

    assets_resp = await client.get(f"/api/tags/{tag_id}/assets", headers=_auth(token))
    assert assets_resp.status_code == 200
    assert [a["symbol"] for a in assets_resp.json()] == [tag_assets[0].symbol]

    renamed = await client.patch(
        f"/api/tags/{tag_id}", json={"name": "dochodowe"}, headers=_auth(token)
    )
    assert renamed.status_code == 200
    # Zmiana samej nazwy NIE kasuje koloru ani powiązań.
    assert renamed.json()["color"] == "#00ff00"
    assert renamed.json()["asset_count"] == 1

    cleared = await client.patch(f"/api/tags/{tag_id}", json={"color": None}, headers=_auth(token))
    assert cleared.status_code == 200
    assert cleared.json()["color"] is None

    detach = await client.delete(
        f"/api/tags/{tag_id}/assets/{tag_assets[0].id}", headers=_auth(token)
    )
    assert detach.status_code == 204
    # 204 także wtedy, gdy powiązania już nie ma — stan końcowy jest ten sam.
    detach_again = await client.delete(
        f"/api/tags/{tag_id}/assets/{tag_assets[0].id}", headers=_auth(token)
    )
    assert detach_again.status_code == 204

    deleted = await client.delete(f"/api/tags/{tag_id}", headers=_auth(token))
    assert deleted.status_code == 204
    assert (await client.get("/api/tags", headers=_auth(token))).json() == []


async def test_duplikat_nazwy_to_409_a_nie_500(client: AsyncClient) -> None:
    token = await _register_and_login(client, EMAIL_A)
    await _create_tag(client, token, "dywidendowe")

    resp = await client.post("/api/tags", json={"name": "dywidendowe"}, headers=_auth(token))

    assert resp.status_code == 409, resp.text


async def test_ta_sama_nazwa_tagu_u_dwoch_uzytkownikow_jest_dozwolona(
    client: AsyncClient, tag_assets: list[Asset]
) -> None:
    """Nazwa jest unikalna **w obrębie użytkownika**. Gdyby była globalna,
    pierwsza osoba, która założy „dywidendowe", zablokowałaby ją wszystkim."""
    token_a = await _register_and_login(client, EMAIL_A)
    token_b = await _register_and_login(client, EMAIL_B)

    tag_a = await _create_tag(client, token_a, "dywidendowe")
    tag_b = await _create_tag(client, token_b, "dywidendowe")
    assert tag_a != tag_b

    await client.put(f"/api/tags/{tag_a}/assets/{tag_assets[0].id}", headers=_auth(token_a))

    # B widzi swój pusty tag, nie cudze powiązanie na tym samym aktywie.
    listed_b = await client.get("/api/tags", headers=_auth(token_b))
    assert [(t["name"], t["asset_count"]) for t in listed_b.json()] == [("dywidendowe", 0)]


async def test_cudzy_tag_to_404_a_nie_403(client: AsyncClient) -> None:
    token_a = await _register_and_login(client, EMAIL_A)
    token_b = await _register_and_login(client, EMAIL_B)
    tag_a = await _create_tag(client, token_a, "dywidendowe")

    resp = await client.get(f"/api/tags/{tag_a}/assets", headers=_auth(token_b))

    # 404, nie 403 — nie zdradzamy nawet istnienia cudzego zasobu.
    assert resp.status_code == 404, resp.text


async def test_nieistniejace_aktywo_to_404_a_nie_500(client: AsyncClient) -> None:
    token = await _register_and_login(client, EMAIL_A)
    tag_id = await _create_tag(client, token, "dywidendowe")

    resp = await client.put(f"/api/tags/{tag_id}/assets/{uuid.uuid4()}", headers=_auth(token))

    assert resp.status_code == 404, resp.text


async def test_filtr_tagow_zaweza_alokacje_i_nie_myli_sie_z_cache(
    client: AsyncClient, tag_assets: list[Asset]
) -> None:
    """Ten sam portfel, ten sam `by`, dwa różne pytania.

    Filtr musi być osobnym segmentem klucza cache — inaczej drugie
    zapytanie dostałoby zapamiętaną odpowiedź na pierwsze.
    """
    token = await _register_and_login(client, EMAIL_A)
    portfolio = await client.post(
        "/api/portfolios", json={"name": "Portfel tagów", "type": "standard"}, headers=_auth(token)
    )
    portfolio_id = portfolio.json()["id"]
    for asset in tag_assets:
        resp = await client.post(
            f"/api/portfolios/{portfolio_id}/holdings",
            json={"asset_id": str(asset.id), "quantity": "1"},
            headers=_auth(token),
        )
        assert resp.status_code == 201, resp.text

    tag_id = await _create_tag(client, token, "dywidendowe")
    await client.put(f"/api/tags/{tag_id}/assets/{tag_assets[0].id}", headers=_auth(token))

    unfiltered = await client.get(
        f"/api/portfolios/{portfolio_id}/allocation?by=market", headers=_auth(token)
    )
    assert unfiltered.status_code == 200, unfiltered.text
    assert {b["key"] for b in unfiltered.json()["buckets"]} == {"GPW", "US"}

    filtered = await client.get(
        f"/api/portfolios/{portfolio_id}/allocation?by=market&tags=dywidendowe",
        headers=_auth(token),
    )
    assert filtered.status_code == 200, filtered.text
    buckets = filtered.json()["buckets"]
    assert [b["key"] for b in buckets] == ["GPW"]
    # Wagi sumują się do 100% w obrębie tego, co filtr przepuścił.
    assert buckets[0]["weight"] == "1.0000"


async def test_zmiana_powiazan_tagu_nie_zostaje_w_cache(
    client: AsyncClient, tag_assets: list[Asset]
) -> None:
    """Odpięcie aktywa od tagu ma być widoczne od razu, nie po TTL.

    Klucz cache nie zmienia się przy edycji `asset_tags` sam z siebie:
    `holdings_version` bumpuje tylko CRUD `holdings`, a `eod_marker` to
    `MAX(prices.date)`. Bez znacznika wersji powiązań ten test dostałby
    w drugim zapytaniu wagi policzone ze składem sprzed odpięcia.
    """
    token = await _register_and_login(client, EMAIL_A)
    portfolio = await client.post(
        "/api/portfolios", json={"name": "Portfel tagów", "type": "standard"}, headers=_auth(token)
    )
    portfolio_id = portfolio.json()["id"]
    for asset in tag_assets:
        await client.post(
            f"/api/portfolios/{portfolio_id}/holdings",
            json={"asset_id": str(asset.id), "quantity": "1"},
            headers=_auth(token),
        )

    tag_id = await _create_tag(client, token, "dywidendowe")
    for asset in tag_assets:
        await client.put(f"/api/tags/{tag_id}/assets/{asset.id}", headers=_auth(token))

    url = f"/api/portfolios/{portfolio_id}/allocation?by=market&tags=dywidendowe"
    first = await client.get(url, headers=_auth(token))
    assert {b["key"] for b in first.json()["buckets"]} == {"GPW", "US"}

    await client.delete(f"/api/tags/{tag_id}/assets/{tag_assets[1].id}", headers=_auth(token))

    second = await client.get(url, headers=_auth(token))
    assert [b["key"] for b in second.json()["buckets"]] == ["GPW"], (
        "kalendarz wag oddał wynik sprzed odpięcia aktywa od tagu"
    )


async def test_nazwa_tagu_nie_moze_udawac_braku_filtra(
    client: AsyncClient, tag_assets: list[Asset]
) -> None:
    """Sentynel „bez filtra" w kluczu cache musi być nieosiągalny jako nazwa.

    Wcześniej był nim `-`, czyli poprawna nazwa tagu: `?tags=-` zapisywał
    pustą alokację pod kluczem zapytania BEZ filtra i przez cały TTL widok
    struktury pokazywał pusty portfel.
    """
    token = await _register_and_login(client, EMAIL_A)
    portfolio = await client.post(
        "/api/portfolios", json={"name": "Portfel tagów", "type": "standard"}, headers=_auth(token)
    )
    portfolio_id = portfolio.json()["id"]
    await client.post(
        f"/api/portfolios/{portfolio_id}/holdings",
        json={"asset_id": str(tag_assets[0].id), "quantity": "1"},
        headers=_auth(token),
    )

    poisoned = await client.get(
        f"/api/portfolios/{portfolio_id}/allocation?by=market&tags=-", headers=_auth(token)
    )
    assert poisoned.json()["buckets"] == []

    clean = await client.get(
        f"/api/portfolios/{portfolio_id}/allocation?by=market", headers=_auth(token)
    )
    assert [b["key"] for b in clean.json()["buckets"]] == ["GPW"], (
        "zapytanie z filtrem zatruło wpis cache zapytania bez filtra"
    )


async def test_zbyt_dluga_lista_tagow_to_422(client: AsyncClient, tag_assets: list[Asset]) -> None:
    """Ciche obcięcie oddawałoby wynik innego pytania niż zadane."""
    token = await _register_and_login(client, EMAIL_A)
    portfolio = await client.post(
        "/api/portfolios", json={"name": "Portfel tagów", "type": "standard"}, headers=_auth(token)
    )
    portfolio_id = portfolio.json()["id"]
    names = ",".join(f"tag{i}" for i in range(21))

    resp = await client.get(
        f"/api/portfolios/{portfolio_id}/allocation?by=market&tags={names}", headers=_auth(token)
    )

    assert resp.status_code == 422, resp.text


async def test_pusty_parametr_tags_znaczy_brak_filtra(
    client: AsyncClient, tag_assets: list[Asset]
) -> None:
    """`?tags=` to wyczyszczony input, a nie „filtr, który nic nie
    przepuszcza" — inaczej wyczyszczenie pola dawałoby pusty ekran."""
    token = await _register_and_login(client, EMAIL_A)
    portfolio = await client.post(
        "/api/portfolios", json={"name": "Portfel tagów", "type": "standard"}, headers=_auth(token)
    )
    portfolio_id = portfolio.json()["id"]
    await client.post(
        f"/api/portfolios/{portfolio_id}/holdings",
        json={"asset_id": str(tag_assets[0].id), "quantity": "1"},
        headers=_auth(token),
    )

    resp = await client.get(
        f"/api/portfolios/{portfolio_id}/allocation?by=market&tags=", headers=_auth(token)
    )

    assert resp.status_code == 200, resp.text
    assert [b["key"] for b in resp.json()["buckets"]] == ["GPW"]


async def test_nieznana_nazwa_tagu_nie_jest_bledem(
    client: AsyncClient, tag_assets: list[Asset]
) -> None:
    """Tag mógł zniknąć w innej karcie przeglądarki. Wynik jest pusty,
    ale odpowiedź jest poprawna — 200, nie 404."""
    token = await _register_and_login(client, EMAIL_A)
    portfolio = await client.post(
        "/api/portfolios", json={"name": "Portfel tagów", "type": "standard"}, headers=_auth(token)
    )
    portfolio_id = portfolio.json()["id"]
    await client.post(
        f"/api/portfolios/{portfolio_id}/holdings",
        json={"asset_id": str(tag_assets[0].id), "quantity": "1"},
        headers=_auth(token),
    )

    resp = await client.get(
        f"/api/portfolios/{portfolio_id}/allocation?by=market&tags=nie-ma-takiego",
        headers=_auth(token),
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["buckets"] == []
