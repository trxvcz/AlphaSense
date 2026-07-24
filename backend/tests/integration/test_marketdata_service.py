"""Testy `ensure_asset_metadata` (`app.modules.marketdata.service`) — plan
krok 22, etap 4.

Integracyjny (prawdziwa baza — `asset`/`asset_source_map`), `YFinanceProvider.
get_metadata` mockowany na poziomie metody (nie sieci — zero sieci w
testach domyślnych), zgodnie z tym, że `service.py` nie jest miejscem, gdzie
testujemy parsowanie odpowiedzi yfinance (to `tests/unit/
test_yfinance_provider.py`), tylko logikę „kiedy w ogóle wywołać providera
i co zrobić z wynikiem".
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.marketdata.models import Asset, AssetSourceMap
from app.modules.marketdata.providers.base import AssetMetadata
from app.modules.marketdata.providers.yfinance import YFinanceProvider
from app.modules.marketdata.service import ensure_asset_metadata


@pytest_asyncio.fixture
async def temp_asset(db_session: AsyncSession) -> AsyncGenerator[Asset, None]:
    asset = Asset(
        symbol=f"TEST-{uuid.uuid4().hex[:8]}",
        name="Test Asset (tymczasowy, test ensure_asset_metadata)",
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


async def test_ensure_asset_metadata_fills_sector_and_country_from_yfinance(
    db_session: AsyncSession, temp_asset: Asset, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_session.add(
        AssetSourceMap(
            asset_id=temp_asset.id, provider="yfinance", provider_symbol="AAPL", priority=1
        )
    )
    await db_session.commit()

    async def fake_get_metadata(self: YFinanceProvider, symbol: str) -> AssetMetadata:
        assert symbol == "AAPL"
        return AssetMetadata(
            symbol="AAPL",
            name="Apple Inc.",
            sector="Technology",
            country="USA",
            asset_class="EQUITY",
        )

    monkeypatch.setattr(YFinanceProvider, "get_metadata", fake_get_metadata)

    await ensure_asset_metadata(db_session, temp_asset)

    assert temp_asset.sector == "Technology"
    assert temp_asset.country == "USA"
    assert temp_asset.metadata_source == "yfinance"


async def test_ensure_asset_metadata_skips_when_already_complete(
    db_session: AsyncSession, temp_asset: Asset, monkeypatch: pytest.MonkeyPatch
) -> None:
    temp_asset.sector = "Gaming"
    temp_asset.country = "Polska"
    await db_session.commit()

    async def fail_if_called(self: YFinanceProvider, symbol: str) -> AssetMetadata:
        raise AssertionError("nie powinno wywołać providera, gdy dane już są uzupełnione")

    monkeypatch.setattr(YFinanceProvider, "get_metadata", fail_if_called)

    await ensure_asset_metadata(db_session, temp_asset)

    assert temp_asset.sector == "Gaming"
    assert temp_asset.country == "Polska"


async def test_ensure_asset_metadata_noop_without_source_mapping(
    db_session: AsyncSession, temp_asset: Asset
) -> None:
    await ensure_asset_metadata(db_session, temp_asset)

    assert temp_asset.sector is None
    assert temp_asset.country is None
    assert temp_asset.metadata_source is None


async def test_ensure_asset_metadata_swallows_provider_failure(
    db_session: AsyncSession, temp_asset: Asset, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_session.add(
        AssetSourceMap(
            asset_id=temp_asset.id, provider="yfinance", provider_symbol="AAPL", priority=1
        )
    )
    await db_session.commit()

    async def fake_get_metadata_raises(self: YFinanceProvider, symbol: str) -> AssetMetadata:
        raise RuntimeError("yfinance milczy")

    monkeypatch.setattr(YFinanceProvider, "get_metadata", fake_get_metadata_raises)

    await ensure_asset_metadata(db_session, temp_asset)  # nie podnosi wyjątku

    assert temp_asset.sector is None
    assert temp_asset.metadata_source is None
