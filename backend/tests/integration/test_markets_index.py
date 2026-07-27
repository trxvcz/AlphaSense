"""Testy `GET /markets/{code}/index?range=` (plan krok 30, etap 6, ADR-102).

Trasa **publiczna** (bez `Authorization`) — patrz docstring
`modules/marketdata/routes.py`: `market_code` nie jest zasobem użytkownika,
tak jak `/assets/search`/`/meta/freshness`. `code` nie jest w
`tests/test_isolation.py::RESOURCE_PARAMS` — świadomie, harness izolacji nie
powinien i nie będzie próbował go łapać (nie ma czego izolować, nie ma
właściciela indeksu).

Podmiana `Market("GPW").index_asset_id` na świeże testowe aktywo (ten sam
wzorzec co `gpw_temp_index` w `tests/integration/test_analytics.py`) — nie
dotykamy prawdziwego WIG20 (dane współdzielone z innymi testami i workerem
EOD).
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from datetime import timedelta
from decimal import Decimal

import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.marketdata.models import Asset, Market, Price
from app.modules.portfolio.service import today


@pytest_asyncio.fixture
async def gpw_temp_index(db_session: AsyncSession) -> AsyncGenerator[Asset, None]:
    """Podmienia tymczasowo `Market("GPW").index_asset_id` na świeże,
    testowe aktywo z kontrolowaną serią `prices`; przywraca oryginalny
    `index_asset_id` po teście (patrz docstring modułu i analogiczna
    fixture w `tests/integration/test_analytics.py`)."""
    market = await db_session.get(Market, "GPW")
    assert market is not None, "Rynek GPW musi istnieć w słowniku (make seed)"
    original_index_asset_id = market.index_asset_id

    suffix = uuid.uuid4().hex[:8]
    temp_index = Asset(
        symbol=f"IDXT{suffix}",
        name=f"Testowy indeks GPW {suffix}",
        asset_class="index",
        market_code="GPW",
        currency="PLN",
    )
    db_session.add(temp_index)
    await db_session.commit()
    await db_session.refresh(temp_index)

    market.index_asset_id = temp_index.id
    await db_session.commit()

    yield temp_index

    market.index_asset_id = original_index_asset_id
    await db_session.commit()
    await db_session.execute(delete(Price).where(Price.asset_id == temp_index.id))
    await db_session.execute(delete(Asset).where(Asset.id == temp_index.id))
    await db_session.commit()


async def test_market_index_happy_path_ascending_series(
    client: AsyncClient, db_session: AsyncSession, gpw_temp_index: Asset
) -> None:
    d = today()
    yesterday = d - timedelta(days=1)
    db_session.add_all(
        [
            Price(asset_id=gpw_temp_index.id, date=yesterday, close_adj=Decimal("2000")),
            Price(asset_id=gpw_temp_index.id, date=d, close_adj=Decimal("2100")),
        ]
    )
    await db_session.commit()

    resp = await client.get("/api/markets/GPW/index")

    assert resp.status_code == 200
    body = resp.json()
    assert [p["date"] for p in body] == [yesterday.isoformat(), d.isoformat()]
    assert Decimal(body[0]["close_adj"]) == Decimal("2000.00000000")
    assert Decimal(body[-1]["close_adj"]) == Decimal("2100.00000000")


async def test_market_index_does_not_require_auth_header(
    client: AsyncClient, db_session: AsyncSession, gpw_temp_index: Asset
) -> None:
    """Trasa publiczna — żądanie bez nagłówka `Authorization` (`client`
    fixture nigdy go tu nie dokłada) dostaje `200`, nigdy `401` (patrz
    docstring modułu, `assets`/`markets` to słowniki globalne)."""
    db_session.add(Price(asset_id=gpw_temp_index.id, date=today(), close_adj=Decimal("2000")))
    await db_session.commit()

    resp = await client.get("/api/markets/GPW/index")

    assert resp.status_code == 200


async def test_market_index_range_filters_lower_bound(
    client: AsyncClient, db_session: AsyncSession, gpw_temp_index: Asset
) -> None:
    d = today()
    old = d - timedelta(days=400)  # poza zakresem 1Y
    db_session.add_all(
        [
            Price(asset_id=gpw_temp_index.id, date=old, close_adj=Decimal("1000")),
            Price(asset_id=gpw_temp_index.id, date=d, close_adj=Decimal("2100")),
        ]
    )
    await db_session.commit()

    resp = await client.get("/api/markets/GPW/index", params={"range": "1Y"})

    assert resp.status_code == 200
    body = resp.json()
    assert [p["date"] for p in body] == [d.isoformat()]


async def test_market_index_unknown_range_is_422(
    client: AsyncClient, gpw_temp_index: Asset
) -> None:
    resp = await client.get("/api/markets/GPW/index", params={"range": "nope"})

    assert resp.status_code == 422


async def test_market_index_unknown_market_code_is_404(client: AsyncClient) -> None:
    resp = await client.get("/api/markets/NIEISTNIEJACY/index")

    assert resp.status_code == 404


async def test_market_index_market_without_index_asset_is_404(client: AsyncClient) -> None:
    """`FX` istnieje w słowniku `markets`, ale `index_asset_id is None`
    (kursy walut nie mają indeksu referencyjnego, `app/db/seed.py`) — to
    brak *pojęcia* indeksu, nie brak danych, więc `404`, nie `200 []`
    (patrz decyzja w raporcie zadania i docstring
    `service.get_market_index_series`)."""
    resp = await client.get("/api/markets/FX/index")

    assert resp.status_code == 404
