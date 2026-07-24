"""Testy `GET /assets/search` — plan krok 24, etap 4.

Integracyjne (prawdziwa baza, jak `db_session`/`client` w `conftest.py`).
Dane testowe są własne (`temp_assets`), niezależne od tego, co zostawił
`make seed` w tabeli `assets` (CDR/PKN/AAPL/MSFT/...) — świadomie, żeby test
nie polegał na treści seedu produkcyjnego (może się zmienić) ani na tym, czy
seed w ogóle został uruchomiony w środowisku testowym. Symbole testowe mają
losowy sufiks (`uuid4().hex[:8]`), żeby kolejne przebiegi testu się nie
depczyły i żeby `ILIKE '%q%'` w teście "znajduje CDR" trafiał wyłącznie w
dane utworzone przez ten test, nie w prawdziwy seed.

Endpoint jest publiczny (bez `Authorization`) — patrz docstring
`app/modules/marketdata/routes.py`.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.marketdata import service as marketdata_service
from app.modules.marketdata.models import Asset


@pytest_asyncio.fixture
async def temp_assets(db_session: AsyncSession) -> AsyncGenerator[list[Asset], None]:
    """Trzy aktywa tymczasowe: dwa trafiające w `q="cdr<sufiks>"` (jeden z
    kompletem `sector`/`country`, jeden bez), jedno spoza wyniku wyszukiwania.
    """
    suffix = uuid.uuid4().hex[:8]
    assets = [
        Asset(
            symbol=f"CDR{suffix}",
            name=f"CD Projekt Test {suffix}",
            asset_class="equity",
            market_code="GPW",
            currency="PLN",
            # bez sector/country — kandydat do uzupełnienia metadanych w tle
        ),
        Asset(
            symbol=f"CDX{suffix}",
            name=f"Inny Emitent Test {suffix}",
            asset_class="equity",
            market_code="GPW",
            currency="PLN",
            sector="gaming",
            country="Polska",
        ),
        Asset(
            symbol=f"ZZZ{suffix}",
            name=f"Niepowiązane Aktywo {suffix}",
            asset_class="equity",
            market_code="US",
            currency="USD",
        ),
    ]
    for asset in assets:
        db_session.add(asset)
    await db_session.commit()
    for asset in assets:
        await db_session.refresh(asset)
    yield assets
    for asset in assets:
        await db_session.execute(delete(Asset).where(Asset.id == asset.id))
    await db_session.commit()


async def test_search_finds_asset_by_symbol_case_insensitive(
    client: AsyncClient, temp_assets: list[Asset]
) -> None:
    cdr, cdx, unrelated = temp_assets

    resp = await client.get("/api/assets/search", params={"q": cdr.symbol.lower()})

    assert resp.status_code == 200
    ids = {row["id"] for row in resp.json()}
    assert str(cdr.id) in ids
    assert str(cdx.id) not in ids
    assert str(unrelated.id) not in ids


async def test_search_finds_asset_by_name_substring(
    client: AsyncClient, temp_assets: list[Asset]
) -> None:
    cdr, _cdx, _unrelated = temp_assets

    resp = await client.get("/api/assets/search", params={"q": "CD Projekt Test"})

    assert resp.status_code == 200
    body = resp.json()
    match = next(row for row in body if row["id"] == str(cdr.id))
    assert match["symbol"] == cdr.symbol
    assert match["name"] == cdr.name
    assert match["asset_class"] == "equity"
    assert match["market_code"] == "GPW"
    assert match["currency"] == "PLN"


async def test_search_with_query_too_short_is_422(client: AsyncClient) -> None:
    resp = await client.get("/api/assets/search", params={"q": "a"})
    assert resp.status_code == 422


async def test_search_with_missing_query_is_422(client: AsyncClient) -> None:
    resp = await client.get("/api/assets/search")
    assert resp.status_code == 422


async def test_search_with_no_matches_returns_empty_list(client: AsyncClient) -> None:
    resp = await client.get(
        "/api/assets/search", params={"q": f"nic-nie-pasuje-{uuid.uuid4().hex[:8]}"}
    )
    assert resp.status_code == 200
    assert resp.json() == []


async def test_search_schedules_metadata_backfill_only_for_incomplete_assets(
    client: AsyncClient,
    temp_assets: list[Asset],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Aktywo bez `sector`/`country` (`cdr`) dostaje zadanie w tle, aktywo z
    kompletem metadanych (`cdx`) — nie. Odpowiedź HTTP nie czeka na to
    zadanie (`BackgroundTasks`, patrz docstring `routes.search_assets`);
    w tym teście, dzięki `ASGITransport` w procesie, zadanie w tle kończy
    się zanim `client.get` odda kontrolę, więc można je asercjonować od razu.
    """
    cdr, cdx, _unrelated = temp_assets
    calls: list[uuid.UUID] = []

    async def fake_refresh(asset_id: uuid.UUID) -> None:
        calls.append(asset_id)

    monkeypatch.setattr(marketdata_service, "refresh_asset_metadata_background", fake_refresh)

    resp = await client.get("/api/assets/search", params={"q": cdr.symbol[:6]})

    assert resp.status_code == 200
    assert cdr.id in calls
    assert cdx.id not in calls
