"""Testy `get_provider_symbol` (`app.modules.marketdata.repository`) — plan
krok 22, etap 4.

Osobny plik od `test_marketdata_repository.py` (funkcje kroku 21, budowane
równolegle) — świadomie, żeby dwaj autorzy dopisujący testy do repozytorium
w tym samym czasie nie konfliktowali się na tym samym pliku testowego
(ten sam powód co konwencja „osobne funkcje" w `repository.py` samym).
Test integracyjny (prawdziwa baza), bo to zwykłe zapytanie SQL.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator

import pytest_asyncio
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.marketdata.models import Asset, AssetSourceMap
from app.modules.marketdata.repository import get_provider_symbol


@pytest_asyncio.fixture
async def temp_asset(db_session: AsyncSession) -> AsyncGenerator[Asset, None]:
    asset = Asset(
        symbol=f"TEST-{uuid.uuid4().hex[:8]}",
        name="Test Asset (tymczasowy, test get_provider_symbol)",
        asset_class="equity",
        market_code="US",
        currency="USD",
    )
    db_session.add(asset)
    await db_session.commit()
    await db_session.refresh(asset)
    yield asset
    await db_session.execute(delete(AssetSourceMap).where(AssetSourceMap.asset_id == asset.id))
    await db_session.execute(delete(Asset).where(Asset.id == asset.id))
    await db_session.commit()


async def test_get_provider_symbol_returns_mapped_symbol(
    db_session: AsyncSession, temp_asset: Asset
) -> None:
    db_session.add(
        AssetSourceMap(
            asset_id=temp_asset.id, provider="yfinance", provider_symbol="AAPL", priority=1
        )
    )
    await db_session.commit()

    symbol = await get_provider_symbol(db_session, temp_asset.id, "yfinance")

    assert symbol == "AAPL"


async def test_get_provider_symbol_distinguishes_providers_for_same_asset(
    db_session: AsyncSession, temp_asset: Asset
) -> None:
    """CDR (GPW) != CDR.WA (Stooq) != CDPROJEKT (Finnhub) — reguła 4:
    „Symbol zewnętrzny nigdy nie jest sklejany w kodzie", więc każdy
    dostawca ma swój własny wiersz mapowania."""
    db_session.add_all(
        [
            AssetSourceMap(
                asset_id=temp_asset.id, provider="stooq", provider_symbol="cdr", priority=1
            ),
            AssetSourceMap(
                asset_id=temp_asset.id, provider="yfinance", provider_symbol="CDR.WA", priority=2
            ),
        ]
    )
    await db_session.commit()

    stooq_symbol = await get_provider_symbol(db_session, temp_asset.id, "stooq")
    yfinance_symbol = await get_provider_symbol(db_session, temp_asset.id, "yfinance")

    assert stooq_symbol == "cdr"
    assert yfinance_symbol == "CDR.WA"
    assert stooq_symbol != yfinance_symbol


async def test_get_provider_symbol_returns_none_when_no_mapping(
    db_session: AsyncSession, temp_asset: Asset
) -> None:
    symbol = await get_provider_symbol(db_session, temp_asset.id, "binance")
    assert symbol is None
