"""Testy `/portfolios/{id}/allocation`, `/portfolios/{id}/concentration`
(plan krok 29, etap 6).

Integracyjne, prawdziwa baza — ten sam wzorzec co
`tests/integration/test_holdings.py`: aktywa/ceny/kursy testowe na
`market_code` już obecnych w słowniku (`GPW` PLN, `US` USD), losowy sufiks
symbolu, sprzątanie po każdym teście. Logika grupowania/HHI ma już pełne
pokrycie w `tests/unit/test_analytics.py` (bez bazy) — te testy sprawdzają
tylko orkiestrację: autoryzację (`get_owned_portfolio`), serializację
odpowiedzi HTTP, 422 na nieznany `by`.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from decimal import Decimal

import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.marketdata.models import Asset, FxRate, Price
from app.modules.portfolio.models import Holding
from app.modules.portfolio.service import today

EMAIL_A = "analytics-a@example.com"
EMAIL_B = "analytics-b@example.com"
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


@dataclass
class AnalyticsAssets:
    equity_pl: Asset  # GPW/PLN, klasa "equity", sektor "Technologia"
    etf_us: Asset  # US/USD, klasa "etf", sektor "Finanse" — dla approximate=true


@pytest_asyncio.fixture
async def analytics_assets(db_session: AsyncSession) -> AsyncGenerator[AnalyticsAssets, None]:
    suffix = uuid.uuid4().hex[:8]
    equity_pl = Asset(
        symbol=f"ANLE{suffix}",
        name=f"Analytics Equity PL {suffix}",
        asset_class="equity",
        market_code="GPW",
        currency="PLN",
        sector="Technologia",
        country="Polska",
    )
    etf_us = Asset(
        symbol=f"ANLF{suffix}",
        name=f"Analytics ETF US {suffix}",
        asset_class="etf",
        market_code="US",
        currency="USD",
        sector="Finanse",
        country="USA",
    )
    db_session.add_all([equity_pl, etf_us])
    await db_session.commit()
    await db_session.refresh(equity_pl)
    await db_session.refresh(etf_us)

    d = today()
    db_session.add_all(
        [
            Price(asset_id=equity_pl.id, date=d, close=Decimal("50"), close_adj=Decimal("50")),
            Price(asset_id=etf_us.id, date=d, close=Decimal("100"), close_adj=Decimal("100")),
        ]
    )
    fx_created_here = await db_session.get(FxRate, ("USD", d)) is None
    if fx_created_here:
        db_session.add(FxRate(currency="USD", date=d, rate_pln=Decimal("4")))
    await db_session.commit()

    yield AnalyticsAssets(equity_pl=equity_pl, etf_us=etf_us)

    asset_ids = [equity_pl.id, etf_us.id]
    await db_session.execute(delete(Holding).where(Holding.asset_id.in_(asset_ids)))
    await db_session.execute(delete(Price).where(Price.asset_id.in_(asset_ids)))
    if fx_created_here:
        await db_session.execute(delete(FxRate).where(FxRate.currency == "USD", FxRate.date == d))
    await db_session.execute(delete(Asset).where(Asset.id.in_(asset_ids)))
    await db_session.commit()


async def _add_holding(
    client: AsyncClient, token: str, portfolio_id: str, asset_id: uuid.UUID, quantity: str
) -> None:
    resp = await client.post(
        f"/api/portfolios/{portfolio_id}/holdings",
        json={"asset_id": str(asset_id), "quantity": quantity},
        headers=_auth(token),
    )
    assert resp.status_code == 201, resp.text


# ---------------------------------------------------------------------------
# GET /portfolios/{id}/allocation
# ---------------------------------------------------------------------------


async def test_allocation_by_class_happy_path(
    client: AsyncClient, analytics_assets: AnalyticsAssets
) -> None:
    token = await _register_and_login(client, EMAIL_A)
    portfolio_id = await _create_portfolio(client, token)
    await _add_holding(client, token, portfolio_id, analytics_assets.equity_pl.id, "10")  # 500 PLN
    await _add_holding(client, token, portfolio_id, analytics_assets.etf_us.id, "1")  # 400 PLN

    resp = await client.get(
        f"/api/portfolios/{portfolio_id}/allocation",
        params={"by": "class"},
        headers=_auth(token),
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["by"] == "class"
    assert body["approximate"] is False  # klasa nie jest przybliżeniem, nawet z ETF w portfelu
    total_weight = sum(Decimal(b["weight"]) for b in body["buckets"])
    assert total_weight == Decimal("1")
    by_key = {b["key"]: b for b in body["buckets"]}
    assert Decimal(by_key["equity"]["value_pln"]) == Decimal("500.00000000")
    assert Decimal(by_key["etf"]["value_pln"]) == Decimal("400.00000000")


async def test_allocation_by_sector_is_approximate_with_etf(
    client: AsyncClient, analytics_assets: AnalyticsAssets
) -> None:
    token = await _register_and_login(client, EMAIL_A)
    portfolio_id = await _create_portfolio(client, token)
    await _add_holding(client, token, portfolio_id, analytics_assets.equity_pl.id, "10")
    await _add_holding(client, token, portfolio_id, analytics_assets.etf_us.id, "1")

    resp = await client.get(
        f"/api/portfolios/{portfolio_id}/allocation",
        params={"by": "sector"},
        headers=_auth(token),
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["approximate"] is True
    keys = {b["key"] for b in body["buckets"]}
    assert keys == {"Technologia", "Finanse"}


async def test_allocation_empty_portfolio_returns_empty_buckets(client: AsyncClient) -> None:
    token = await _register_and_login(client, EMAIL_A)
    portfolio_id = await _create_portfolio(client, token)

    resp = await client.get(
        f"/api/portfolios/{portfolio_id}/allocation",
        params={"by": "class"},
        headers=_auth(token),
    )

    assert resp.status_code == 200
    assert resp.json()["buckets"] == []


async def test_allocation_unknown_dimension_is_422(client: AsyncClient) -> None:
    token = await _register_and_login(client, EMAIL_A)
    portfolio_id = await _create_portfolio(client, token)

    resp = await client.get(
        f"/api/portfolios/{portfolio_id}/allocation",
        params={"by": "nope"},
        headers=_auth(token),
    )

    assert resp.status_code == 422


async def test_allocation_missing_by_is_422(client: AsyncClient) -> None:
    token = await _register_and_login(client, EMAIL_A)
    portfolio_id = await _create_portfolio(client, token)

    resp = await client.get(f"/api/portfolios/{portfolio_id}/allocation", headers=_auth(token))

    assert resp.status_code == 422


async def test_allocation_of_other_user_is_404(client: AsyncClient) -> None:
    token_a = await _register_and_login(client, EMAIL_A)
    token_b = await _register_and_login(client, EMAIL_B)
    portfolio_id = await _create_portfolio(client, token_a)

    resp = await client.get(
        f"/api/portfolios/{portfolio_id}/allocation",
        params={"by": "class"},
        headers=_auth(token_b),
    )

    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /portfolios/{id}/concentration
# ---------------------------------------------------------------------------


async def test_concentration_happy_path(
    client: AsyncClient, analytics_assets: AnalyticsAssets
) -> None:
    token = await _register_and_login(client, EMAIL_A)
    portfolio_id = await _create_portfolio(client, token)
    await _add_holding(client, token, portfolio_id, analytics_assets.equity_pl.id, "10")  # 500 PLN
    await _add_holding(client, token, portfolio_id, analytics_assets.etf_us.id, "1")  # 400 PLN
    # wagi: 500/900 i 400/900 -> hhi = (5/9)^2 + (4/9)^2 = 41/81 ≈ 0.5062

    resp = await client.get(f"/api/portfolios/{portfolio_id}/concentration", headers=_auth(token))

    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 2
    assert Decimal(body["hhi"]) == Decimal("0.5062")
    assert Decimal(body["top5_share"]) == Decimal("1")  # tylko 2 pozycje, obie w top5
    assert body["interpretation"] == "wysoka"


async def test_concentration_empty_portfolio_is_zero(client: AsyncClient) -> None:
    token = await _register_and_login(client, EMAIL_A)
    portfolio_id = await _create_portfolio(client, token)

    resp = await client.get(f"/api/portfolios/{portfolio_id}/concentration", headers=_auth(token))

    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 0
    assert Decimal(body["hhi"]) == Decimal("0")
    assert Decimal(body["top5_share"]) == Decimal("0")
    assert body["interpretation"] == "niska"


async def test_concentration_of_other_user_is_404(client: AsyncClient) -> None:
    token_a = await _register_and_login(client, EMAIL_A)
    token_b = await _register_and_login(client, EMAIL_B)
    portfolio_id = await _create_portfolio(client, token_a)

    resp = await client.get(f"/api/portfolios/{portfolio_id}/concentration", headers=_auth(token_b))

    assert resp.status_code == 404
