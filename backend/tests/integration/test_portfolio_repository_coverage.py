"""Testy `held_asset_price_coverage` (etap 8, krok zerowy).

Odpowiada na jedno pytanie: **od którego dnia wycena portfela jest pełna**,
czyli każda trzymana pozycja ma już notowanie. Silnik wyceny pomija pozycję
bez ceny zamiast liczyć ją jako zero (`worker/jobs/snapshot_portfolios.py`),
więc wcześniejsze dni dają wyceny cząstkowe — nieodróżnialne potem od
pełnych. `seed-history` używa tego jako guardu (patrz
`test_cli_seed_history.py`, gdzie ta funkcja jest podmieniana).

Sedno testu: `first_full_date` to **maksimum z minimów** per aktywo, nie
globalne minimum. Pomyłka w tę stronę jest cicha — przepuściłaby dokładnie
te dni, przed którymi guard ma chronić.

Integracyjne, prawdziwa baza. `_clean_auth_tables` z `conftest.py` czyści
`users` CASCADE przed każdym testem, więc portfele/pozycje znikają same;
`Asset`/`Price` sprzątane ręcznie, bo aktywa nie są zasobem użytkownika.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from datetime import date
from decimal import Decimal

import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.models import User
from app.modules.marketdata.models import Asset, Price
from app.modules.portfolio.models import Holding, Portfolio
from app.modules.portfolio.repository import held_asset_price_coverage

PASSWORD = "correct-password-1"


@pytest_asyncio.fixture
async def assets(db_session: AsyncSession) -> AsyncGenerator[list[Asset], None]:
    """Dwa aktywa PLN na `GPW`, bez żadnych cen na starcie."""
    created = []
    for index in range(2):
        asset = Asset(
            symbol=f"COV{index}{uuid.uuid4().hex[:6]}",
            name=f"Test Coverage Asset {index}",
            asset_class="equity",
            market_code="GPW",
            currency="PLN",
        )
        db_session.add(asset)
        created.append(asset)
    await db_session.commit()
    for asset in created:
        await db_session.refresh(asset)

    yield created

    ids = [a.id for a in created]
    # `holdings` przed `assets`: FK `holdings.asset_id -> assets.id` nie ma
    # kaskady w tę stronę (aktywo nie jest zasobem użytkownika, patrz
    # docstring `Holding`), a `_clean_auth_tables` sprząta użytkowników
    # dopiero PRZED następnym testem — tu pozycje jeszcze istnieją.
    await db_session.execute(delete(Holding).where(Holding.asset_id.in_(ids)))
    await db_session.execute(delete(Price).where(Price.asset_id.in_(ids)))
    await db_session.execute(delete(Asset).where(Asset.id.in_(ids)))
    await db_session.commit()


async def _portfolio_with(
    client: AsyncClient, db_session: AsyncSession, assets_: list[Asset]
) -> Portfolio:
    """Portfel z pozycją na każdym z `assets_` (przez API, żeby przejść
    normalną ścieżką tworzenia, a nie wstawiać wierszy na skróty)."""
    email = f"coverage-{uuid.uuid4().hex[:8]}@example.com"
    r = await client.post("/api/auth/register", json={"email": email, "password": PASSWORD})
    assert r.status_code == 201, r.text
    r = await client.post("/api/auth/login", json={"email": email, "password": PASSWORD})
    assert r.status_code == 200, r.text
    token = r.json()["access_token"]

    r = await client.post(
        "/api/portfolios",
        json={"name": "Pokrycie", "type": "standard"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 201, r.text
    portfolio_id = uuid.UUID(r.json()["id"])

    for asset in assets_:
        db_session.add(Holding(portfolio_id=portfolio_id, asset_id=asset.id, quantity=Decimal("1")))
    await db_session.commit()

    portfolio = await db_session.get(Portfolio, portfolio_id)
    assert portfolio is not None
    return portfolio


def _price(asset: Asset, day: date) -> Price:
    return Price(asset_id=asset.id, date=day, close=Decimal("10"), close_adj=Decimal("10"))


async def test_first_full_date_is_max_of_per_asset_minimums(
    client: AsyncClient, db_session: AsyncSession, assets: list[Asset]
) -> None:
    """Aktywo z krótszą historią wyznacza próg dla całego portfela."""
    early, late = assets
    db_session.add_all([_price(early, date(2020, 1, 2)), _price(early, date(2026, 5, 5))])
    db_session.add_all([_price(late, date(2026, 3, 10)), _price(late, date(2026, 5, 5))])
    await db_session.commit()
    await _portfolio_with(client, db_session, assets)

    coverage = await held_asset_price_coverage(db_session)

    assert coverage.assets_without_prices == ()
    assert coverage.is_complete
    assert coverage.first_full_date == date(2026, 3, 10), (
        "próg wyznacza aktywo o NAJPÓŹNIEJSZYM debiucie, nie najwcześniejszym"
    )


async def test_asset_without_any_price_is_reported_and_blocks_full_date(
    client: AsyncClient, db_session: AsyncSession, assets: list[Asset]
) -> None:
    """Pozycja bez ani jednej ceny — dzień pełnego pokrycia nie istnieje."""
    priced, unpriced = assets
    db_session.add(_price(priced, date(2026, 1, 2)))
    await db_session.commit()
    await _portfolio_with(client, db_session, assets)

    coverage = await held_asset_price_coverage(db_session)

    assert coverage.assets_without_prices == (unpriced.symbol,)
    assert coverage.first_full_date is None
    assert not coverage.is_complete


async def test_assets_outside_portfolios_are_ignored(
    client: AsyncClient, db_session: AsyncSession, assets: list[Asset]
) -> None:
    """Aktywo w słowniku, ale nietrzymane przez nikogo, nie wpływa na próg —
    inaczej jeden nienotowany walor w `assets` blokowałby `seed-history`
    wszystkim."""
    held, not_held = assets
    db_session.add(_price(held, date(2026, 2, 2)))
    await db_session.commit()
    await _portfolio_with(client, db_session, [held])

    coverage = await held_asset_price_coverage(db_session)

    assert not_held.symbol not in coverage.assets_without_prices
    assert coverage.first_full_date == date(2026, 2, 2)


async def test_no_holdings_gives_no_coverage_date(
    db_session: AsyncSession, assets: list[Asset]
) -> None:
    """Pusta baza portfeli — nie ma czego pokrywać, więc i progu nie ma."""
    await db_session.execute(delete(User))
    await db_session.commit()

    coverage = await held_asset_price_coverage(db_session)

    assert coverage.assets_without_prices == ()
    assert coverage.first_full_date is None
