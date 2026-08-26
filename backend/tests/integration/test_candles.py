"""Endpoint świecowy `/assets/{id}/candles` (plan krok 45, etap 8).

Trasa jest **publiczna** jak reszta modułu `marketdata` — notowania nie są
zasobem użytkownika. Ten plik pilnuje kontraktu: kwoty jako string, korekta
o splity faktycznie zastosowana do CAŁEJ świecy, `skipped` w odpowiedzi
zamiast cichej dziury w serii.

Indeks rynku jedzie tą samą trasą, bo jest zwykłym aktywem
(`markets.index_asset_id`, ADR-102) — osobnego `/markets/{code}/candles`
świadomie nie ma, byłby endpointem bez konsumenta.
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

from app.modules.marketdata.models import Asset, Price
from app.modules.portfolio.service import today


@pytest_asyncio.fixture
async def candle_asset(db_session: AsyncSession) -> AsyncGenerator[Asset, None]:
    """Aktywo z trzema sesjami: normalną, sprzed splitu 2:1 i niekompletną."""
    suffix = uuid.uuid4().hex[:8]
    asset = Asset(
        symbol=f"CND{suffix}",
        name=f"Candle Test {suffix}",
        asset_class="equity",
        market_code="GPW",
        currency="PLN",
    )
    db_session.add(asset)
    await db_session.commit()
    await db_session.refresh(asset)

    d = today()
    db_session.add_all(
        [
            Price(
                asset_id=asset.id,
                date=d - timedelta(days=2),
                open=Decimal("100"),
                high=Decimal("110"),
                low=Decimal("90"),
                close=Decimal("100"),
                close_adj=Decimal("50"),  # sprzed splitu 2:1
                volume=1000,
            ),
            Price(
                asset_id=asset.id,
                date=d - timedelta(days=1),
                open=Decimal("50"),
                high=Decimal("52"),
                low=Decimal("49"),
                close=Decimal("51"),
                close_adj=Decimal("51"),
                volume=2000,
            ),
            # Wiersz bez kompletu OHLC — nie da się policzyć współczynnika.
            Price(asset_id=asset.id, date=d, close_adj=Decimal("52")),
        ]
    )
    await db_session.commit()

    yield asset

    await db_session.execute(delete(Price).where(Price.asset_id == asset.id))
    await db_session.execute(delete(Asset).where(Asset.id == asset.id))
    await db_session.commit()


async def test_swiece_sa_skorygowane_a_kwoty_to_stringi(
    client: AsyncClient, candle_asset: Asset
) -> None:
    resp = await client.get(f"/api/assets/{candle_asset.id}/candles?range=1M")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["symbol"] == candle_asset.symbol
    assert body["currency"] == "PLN"
    assert body["range"] == "1M"
    assert len(body["candles"]) == 2

    # Dzień sprzed splitu: CAŁA świeca przeskalowana o 0.5, nie samo
    # zamknięcie (CLAUDE.md #4).
    first = body["candles"][0]
    assert first["open"] == "50.00000000"
    assert first["high"] == "55.00000000"
    assert first["low"] == "45.00000000"
    assert first["close"] == "50.00000000"
    # `volume` to sztuki — liczba, nie string, i bez skalowania.
    assert first["volume"] == 1000


async def test_niekompletna_sesja_jest_policzona_a_nie_przemilczana(
    client: AsyncClient, candle_asset: Asset
) -> None:
    """Wykres z dziurą wygląda jak wykres kompletny, więc liczba pominiętych
    dni musi być w odpowiedzi (CLAUDE.md #3.15)."""
    resp = await client.get(f"/api/assets/{candle_asset.id}/candles?range=1M")

    assert resp.json()["skipped"] == 1


async def test_swiece_sa_rosnaco_po_dacie(client: AsyncClient, candle_asset: Asset) -> None:
    dates = [
        c["date"]
        for c in (await client.get(f"/api/assets/{candle_asset.id}/candles?range=1M")).json()[
            "candles"
        ]
    ]

    assert dates == sorted(dates)


async def test_nieznane_aktywo_to_404(client: AsyncClient) -> None:
    resp = await client.get(f"/api/assets/{uuid.uuid4()}/candles")

    assert resp.status_code == 404, resp.text


async def test_nieznany_zakres_to_422(client: AsyncClient, candle_asset: Asset) -> None:
    """`?range=` jest zamkniętym zbiorem, tak samo jak w `/markets/{code}/index`."""
    resp = await client.get(f"/api/assets/{candle_asset.id}/candles?range=7D")

    assert resp.status_code == 422, resp.text
