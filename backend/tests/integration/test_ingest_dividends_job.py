"""Test odporności joba dywidend (plan krok 47, etap 9).

Sprawdza jedną własność, której nie widać w testach dostawcy ani endpointu:
**awaria jednego symbolu nie może zabrać danych pozostałych**. Job ma dobowy
budżet 25 zapytań, więc przebieg, który po ósmym błędzie wyrzuca do kosza
siedem udanych pobrań, spala limit bez żadnego zapisu.

Dostawca jest podstawiony (`_FakeProvider`) — celem testu jest zachowanie
pętli i transakcji, a nie parsowanie odpowiedzi Alpha Vantage (to pokrywa
`tests/unit/test_alphavantage_dividends_provider.py`).
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, cast

import pytest_asyncio
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ProviderUnavailableError
from app.modules.dividends.models import DividendEvent
from app.modules.dividends.providers.base import DividendAnnouncement
from app.modules.marketdata.models import Asset
from app.modules.portfolio.service import today
from worker.jobs.ingest_dividends import _Counters, _ingest_symbol


class _FakeProvider:
    """Zwraca zapowiedzi albo rzuca — zależnie od symbolu."""

    name = "fake_dividends"

    def __init__(self, failing: dict[str, Exception]) -> None:
        self._failing = failing

    async def get_dividends(self, symbol: str) -> list[DividendAnnouncement]:
        error = self._failing.get(symbol)
        if error is not None:
            raise error
        return [
            DividendAnnouncement(
                symbol=symbol,
                ex_date=today() + timedelta(days=5),
                amount=Decimal("0.27"),
                currency="",
            )
        ]


@dataclass(frozen=True)
class _JobAsset:
    """Zwykłe wartości, nie obiekty ORM.

    `_ingest_symbol` commituje, a commit **wygasza** atrybuty instancji ORM —
    kolejny odczyt `asset.id` próbowałby doładować je z bazy w miejscu, gdzie
    SQLAlchemy async tego nie umie (`MissingGreenlet`). Test i tak potrzebuje
    tylko trzech skalarów.
    """

    id: uuid.UUID
    symbol: str
    currency: str


@pytest_asyncio.fixture
async def job_assets(db_session: AsyncSession) -> AsyncGenerator[list[_JobAsset], None]:
    suffix = uuid.uuid4().hex[:8]
    assets = [
        Asset(
            symbol=f"JOB{index}{suffix}",
            name=f"Job asset {index} {suffix}",
            asset_class="equity",
            market_code="US",
            currency="USD",
        )
        for index in (1, 2)
    ]
    db_session.add_all(assets)
    await db_session.commit()
    for asset in assets:
        await db_session.refresh(asset)

    prepared = [_JobAsset(id=a.id, symbol=a.symbol, currency=a.currency) for a in assets]
    asset_ids = [a.id for a in prepared]

    yield prepared

    await db_session.execute(delete(DividendEvent).where(DividendEvent.asset_id.in_(asset_ids)))
    await db_session.execute(delete(Asset).where(Asset.id.in_(asset_ids)))
    await db_session.commit()


async def _ingest_all(db: AsyncSession, provider: _FakeProvider, assets: list[Asset]) -> _Counters:
    counters = _Counters()
    fetched_at = datetime.now(UTC)
    for asset in assets:
        await _ingest_symbol(
            db,
            cast(Any, provider),
            asset_id=asset.id,
            provider_symbol=asset.symbol,
            currency=asset.currency,
            fetched_at=fetched_at,
            counters=counters,
        )
    return counters


async def test_padniety_symbol_nie_kasuje_danych_pozostalych(
    db_session: AsyncSession, job_assets: list[_JobAsset]
) -> None:
    failing, working = job_assets
    provider = _FakeProvider({failing.symbol: ProviderUnavailableError("limit dobowy wyczerpany")})

    counters = await _ingest_all(db_session, provider, [failing, working])

    assert counters.failed_symbols == 1
    assert counters.stored == 1
    stored = (
        (
            await db_session.execute(
                select(DividendEvent.asset_id).where(
                    DividendEvent.asset_id.in_([failing.id, working.id])
                )
            )
        )
        .scalars()
        .all()
    )
    assert stored == [working.id]


async def test_niespodziewany_wyjatek_tez_nie_przerywa_przebiegu(
    db_session: AsyncSession, job_assets: list[_JobAsset]
) -> None:
    """Nie tylko `ProviderUnavailableError`: `get_with_backoff` wypuszcza
    `httpx.HTTPStatusError` wprost, a parser może paść na nieoczekiwanym
    kształcie odpowiedzi. Job dobowy ma dowieźć resztę symboli."""
    failing, working = job_assets
    provider = _FakeProvider({failing.symbol: RuntimeError("nieoczekiwany kształt odpowiedzi")})

    counters = await _ingest_all(db_session, provider, [failing, working])

    assert counters.failed_symbols == 1
    assert counters.stored == 1
