"""Testy `worker.jobs.snapshot_portfolios` — job snapshotów `portfolio_
valuations` po EOD (plan krok 27, etap 5).

Integracyjne, prawdziwa baza (`_clean_auth_tables` w `conftest.py` czyści
`users` CASCADE przed każdym testem — kaskadowo usuwa portfele/pozycje/
snapshoty poprzedniego przebiegu, ten sam wzorzec co `test_holdings.py`).
`priced_asset` to jedyne tymczasowe aktywo tego pliku (PLN na `GPW`,
notowanie na „dziś" — `portfolio_service.today()`), sprzątane ręcznie po
każdym teście, bo `Asset` nie jest zasobem użytkownika (nie kaskaduje z
`users`, patrz docstring `Holding` w `app/modules/portfolio/models.py`).
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from datetime import date, timedelta
from decimal import Decimal

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

import worker.jobs.snapshot_portfolios as snapshot_module
from app.modules.marketdata.models import Asset, Price
from app.modules.portfolio.models import Holding, Portfolio, PortfolioValuation
from app.modules.portfolio.service import PortfolioValue, today
from worker.jobs.snapshot_portfolios import snapshot_portfolios

EMAIL_A = "snapshot-a@example.com"
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


async def _create_portfolio(client: AsyncClient, token: str, name: str = "Portfel") -> str:
    resp = await client.post(
        "/api/portfolios", json={"name": name, "type": "standard"}, headers=_auth(token)
    )
    assert resp.status_code == 201, resp.text
    portfolio_id: str = resp.json()["id"]
    return portfolio_id


@pytest_asyncio.fixture
async def priced_asset(db_session: AsyncSession) -> AsyncGenerator[Asset, None]:
    """Aktywo PLN na `GPW` z notowaniem `close_adj=50` na „dziś" — pozwala
    liczyć `value_pln` bez zależności od kursu NBP (jak `pln_asset` w
    `test_holdings.py`)."""
    suffix = uuid.uuid4().hex[:8]
    asset = Asset(
        symbol=f"SNAP{suffix}",
        name=f"Test Snapshot Asset {suffix}",
        asset_class="equity",
        market_code="GPW",
        currency="PLN",
    )
    db_session.add(asset)
    await db_session.commit()
    await db_session.refresh(asset)

    d = today()
    db_session.add(Price(asset_id=asset.id, date=d, close=Decimal("50"), close_adj=Decimal("50")))
    await db_session.commit()

    yield asset

    await db_session.execute(delete(Holding).where(Holding.asset_id == asset.id))
    await db_session.execute(delete(Price).where(Price.asset_id == asset.id))
    await db_session.execute(delete(Asset).where(Asset.id == asset.id))
    await db_session.commit()


async def test_snapshot_creates_valuation_for_portfolio_with_holding(
    client: AsyncClient, db_session: AsyncSession, priced_asset: Asset
) -> None:
    token = await _register_and_login(client, EMAIL_A)
    portfolio_id = await _create_portfolio(client, token)
    await client.post(
        f"/api/portfolios/{portfolio_id}/holdings",
        json={"asset_id": str(priced_asset.id), "quantity": "10"},
        headers=_auth(token),
    )

    d = today()
    await snapshot_portfolios(run_date=d)

    row = await db_session.get(PortfolioValuation, (uuid.UUID(portfolio_id), d))
    assert row is not None
    assert row.value_pln == Decimal("500")  # 10 × 50 × 1
    assert row.composition_change is True  # holding dodany dzisiaj


async def test_snapshot_second_run_same_day_overwrites_not_duplicates(
    client: AsyncClient, db_session: AsyncSession, priced_asset: Asset
) -> None:
    token = await _register_and_login(client, EMAIL_A)
    portfolio_id = await _create_portfolio(client, token)
    create_resp = await client.post(
        f"/api/portfolios/{portfolio_id}/holdings",
        json={"asset_id": str(priced_asset.id), "quantity": "10"},
        headers=_auth(token),
    )
    holding_id = create_resp.json()["id"]

    d = today()
    await snapshot_portfolios(run_date=d)

    # Zmiana składu tego samego dnia — wartość portfela się zmienia, drugi
    # przebieg snapshotu musi nadpisać wiersz, nie dodać drugiego.
    await client.patch(f"/api/holdings/{holding_id}", json={"quantity": "20"}, headers=_auth(token))
    await snapshot_portfolios(run_date=d)

    result = await db_session.execute(
        select(PortfolioValuation).where(PortfolioValuation.portfolio_id == uuid.UUID(portfolio_id))
    )
    rows = result.scalars().all()
    assert len(rows) == 1  # nadpisany, nie zduplikowany
    assert rows[0].value_pln == Decimal("1000")  # 20 × 50
    assert rows[0].composition_change is True


async def test_snapshot_composition_change_false_for_different_day(
    client: AsyncClient, db_session: AsyncSession, priced_asset: Asset
) -> None:
    token = await _register_and_login(client, EMAIL_A)
    portfolio_id = await _create_portfolio(client, token)
    await client.post(
        f"/api/portfolios/{portfolio_id}/holdings",
        json={"asset_id": str(priced_asset.id), "quantity": "1"},
        headers=_auth(token),
    )

    d = today()
    # `holdings_changed_at` (ustawione przez API na „dziś") ręcznie cofnięte
    # o dzień — symuluje portfel, którego skład zmienił się wcześniej, nie w
    # dniu snapshotu.
    portfolio = await db_session.get(Portfolio, uuid.UUID(portfolio_id))
    assert portfolio is not None
    portfolio.holdings_changed_at = d - timedelta(days=1)
    await db_session.commit()

    await snapshot_portfolios(run_date=d)

    row = await db_session.get(PortfolioValuation, (uuid.UUID(portfolio_id), d))
    assert row is not None
    assert row.composition_change is False


async def test_snapshot_empty_portfolio_zero_value_no_crash(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    token = await _register_and_login(client, EMAIL_A)
    portfolio_id = await _create_portfolio(client, token)

    d = today()
    await snapshot_portfolios(run_date=d)

    row = await db_session.get(PortfolioValuation, (uuid.UUID(portfolio_id), d))
    assert row is not None
    assert row.value_pln == Decimal("0")
    assert row.composition_change is False  # nigdy nie dodano żadnej pozycji


async def test_snapshot_continues_after_one_portfolio_fails(
    client: AsyncClient,
    db_session: AsyncSession,
    priced_asset: Asset,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Wyjątek przy wycenie jednego portfela (zasymulowany monkeypatchem na
    `portfolio_service.current_value`, jedyny realistyczny sposób bez
    ingerencji w `portfolio/service.py`) nie może przerwać reszty przebiegu
    (SKILL `job-eod` reguła 6) — drugi portfel dostaje swój snapshot mimo
    porażki pierwszego."""
    token = await _register_and_login(client, EMAIL_A)
    ok_portfolio_id = await _create_portfolio(client, token, name="OK")
    bad_portfolio_id = await _create_portfolio(client, token, name="Bad")
    await client.post(
        f"/api/portfolios/{ok_portfolio_id}/holdings",
        json={"asset_id": str(priced_asset.id), "quantity": "1"},
        headers=_auth(token),
    )

    real_current_value = snapshot_module.portfolio_service.current_value

    async def fake_current_value(
        db: AsyncSession, portfolio: Portfolio, on_date: date
    ) -> PortfolioValue:
        if str(portfolio.id) == bad_portfolio_id:
            raise RuntimeError("symulowana awaria wyceny")
        return await real_current_value(db, portfolio, on_date)

    monkeypatch.setattr(snapshot_module.portfolio_service, "current_value", fake_current_value)

    d = today()
    await snapshot_module.snapshot_portfolios(run_date=d)

    ok_row = await db_session.get(PortfolioValuation, (uuid.UUID(ok_portfolio_id), d))
    assert ok_row is not None
    assert ok_row.value_pln == Decimal("50")  # 1 × 50

    bad_row = await db_session.get(PortfolioValuation, (uuid.UUID(bad_portfolio_id), d))
    assert bad_row is None  # portfel, który zawiódł, nie ma snapshotu
