"""Testy `/portfolios/{id}/holdings`, `/holdings/{id}`, `/summary`,
`/valuations` — CRUD pozycji, silnik wyceny PLN, bump `holdings_version`
(plan kroki 25-26-28, etap 5).

Integracyjne, prawdziwa baza. Aktywa/ceny/kursy testowe (`temp_assets`)
istnieją tylko na `market_code` już obecnych w słowniku (`GPW` PLN, `US`
USD — jak `tests/integration/test_assets_search.py`/`test_meta_freshness.py`)
— ten plik nie tworzy własnych `markets`, tylko `assets`/`prices`/
`fx_rates` potrzebne do wyceny, z losowym sufiksem symbolu i sprzątaniem
po każdym teście.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal

import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.marketdata.models import Asset, FxRate, Price
from app.modules.portfolio.models import Holding, PortfolioValuation
from app.modules.portfolio.service import today

EMAIL_A = "holdings-a@example.com"
EMAIL_B = "holdings-b@example.com"
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
class TempAssets:
    pln_asset: Asset
    usd_asset: Asset


@pytest_asyncio.fixture
async def temp_assets(db_session: AsyncSession) -> AsyncGenerator[TempAssets, None]:
    """Dwa aktywa tymczasowe (PLN na `GPW`, USD na `US`) wycenione na
    „dziś" (`service.today()`), plus kurs USD/PLN na „dziś" — nie polegamy
    na `fx_rates`/`prices` z realnej ingestii, która może nie sięgać
    bieżącej daty w środowisku testowym."""
    suffix = uuid.uuid4().hex[:8]
    pln_asset = Asset(
        symbol=f"HOLP{suffix}",
        name=f"Test Holding PLN {suffix}",
        asset_class="equity",
        market_code="GPW",
        currency="PLN",
    )
    usd_asset = Asset(
        symbol=f"HOLU{suffix}",
        name=f"Test Holding USD {suffix}",
        asset_class="equity",
        market_code="US",
        currency="USD",
    )
    db_session.add_all([pln_asset, usd_asset])
    await db_session.commit()
    await db_session.refresh(pln_asset)
    await db_session.refresh(usd_asset)

    d = today()
    db_session.add_all(
        [
            Price(asset_id=pln_asset.id, date=d, close=Decimal("50"), close_adj=Decimal("50")),
            Price(asset_id=usd_asset.id, date=d, close=Decimal("100"), close_adj=Decimal("100")),
        ]
    )
    fx_created_here = await db_session.get(FxRate, ("USD", d)) is None
    if fx_created_here:
        db_session.add(FxRate(currency="USD", date=d, rate_pln=Decimal("4")))
    await db_session.commit()

    yield TempAssets(pln_asset=pln_asset, usd_asset=usd_asset)

    asset_ids = [pln_asset.id, usd_asset.id]
    # `Holding.asset_id` nie kaskaduje z `assets` (`models.py`, docstring
    # `Holding`) — testy w tym pliku tworzą `Holding` na te aktywa przez
    # HTTP i same ich nie sprzątają (to nie ich odpowiedzialność), więc
    # trzeba je usunąć tutaj przed aktywem, inaczej `DELETE FROM assets`
    # wywala się na wciąż istniejącym FK z `holdings` (`_clean_auth_tables`
    # w `conftest.py` posprząta resztę — portfele/użytkowników — dopiero
    # przed *następnym* testem, nie przed tym teardownem).
    await db_session.execute(delete(Holding).where(Holding.asset_id.in_(asset_ids)))
    await db_session.execute(delete(Price).where(Price.asset_id.in_(asset_ids)))
    if fx_created_here:
        await db_session.execute(delete(FxRate).where(FxRate.currency == "USD", FxRate.date == d))
    await db_session.execute(delete(Asset).where(Asset.id.in_(asset_ids)))
    await db_session.commit()


# ---------------------------------------------------------------------------
# POST /portfolios/{id}/holdings, GET /portfolios/{id}/holdings
# ---------------------------------------------------------------------------


async def test_create_holding_happy_path_pln_asset(
    client: AsyncClient, temp_assets: TempAssets
) -> None:
    """Aktywo w PLN: `fx_pln` pominięty (żaden `fx_rates` dla PLN nie
    istnieje — gdyby kod błędnie próbował go odpytać, pozycja wyszłaby
    `stale`/`value_pln=None`, więc poprawny wynik dowodzi pominięcia)."""
    token = await _register_and_login(client, EMAIL_A)
    portfolio_id = await _create_portfolio(client, token)

    resp = await client.post(
        f"/api/portfolios/{portfolio_id}/holdings",
        json={"asset_id": str(temp_assets.pln_asset.id), "quantity": "10"},
        headers=_auth(token),
    )

    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["symbol"] == temp_assets.pln_asset.symbol
    assert Decimal(body["quantity"]) == Decimal("10")
    assert Decimal(body["value_pln"]) == Decimal("500")  # 10 × 50 × 1
    assert body["stale"] is False
    assert body["as_of"] == today().isoformat()
    assert body["avg_cost"] is None
    assert body["unrealized_pl"] is None
    assert body["split_suspected"] is False


async def test_create_holding_with_avg_cost_computes_unrealized_pl(
    client: AsyncClient, temp_assets: TempAssets
) -> None:
    token = await _register_and_login(client, EMAIL_A)
    portfolio_id = await _create_portfolio(client, token)

    resp = await client.post(
        f"/api/portfolios/{portfolio_id}/holdings",
        json={
            "asset_id": str(temp_assets.usd_asset.id),
            "quantity": "2",
            "avg_cost": "80",
            "cost_currency": "USD",
        },
        headers=_auth(token),
    )

    assert resp.status_code == 201, resp.text
    body = resp.json()
    # cena PLN/jednostkę = 100 × 4 = 400; koszt PLN/jednostkę = 80 × 4 = 320
    assert Decimal(body["value_pln"]) == Decimal("800")
    assert Decimal(body["unrealized_pl"]) == Decimal("160")


async def test_create_holding_bumps_portfolio_holdings_version(
    client: AsyncClient, temp_assets: TempAssets
) -> None:
    token = await _register_and_login(client, EMAIL_A)
    portfolio_id = await _create_portfolio(client, token)

    before = await client.get(f"/api/portfolios/{portfolio_id}", headers=_auth(token))
    assert before.json()["holdings_version"] == 0

    await client.post(
        f"/api/portfolios/{portfolio_id}/holdings",
        json={"asset_id": str(temp_assets.pln_asset.id), "quantity": "1"},
        headers=_auth(token),
    )

    after = await client.get(f"/api/portfolios/{portfolio_id}", headers=_auth(token))
    assert after.json()["holdings_version"] == 1


async def test_create_holding_duplicate_asset_is_409(
    client: AsyncClient, temp_assets: TempAssets
) -> None:
    token = await _register_and_login(client, EMAIL_A)
    portfolio_id = await _create_portfolio(client, token)
    payload = {"asset_id": str(temp_assets.pln_asset.id), "quantity": "1"}

    first = await client.post(
        f"/api/portfolios/{portfolio_id}/holdings", json=payload, headers=_auth(token)
    )
    assert first.status_code == 201

    second = await client.post(
        f"/api/portfolios/{portfolio_id}/holdings", json=payload, headers=_auth(token)
    )

    assert second.status_code == 409
    assert second.json()["error"]["code"] == "conflict"


async def test_create_holding_unknown_asset_is_422(client: AsyncClient) -> None:
    token = await _register_and_login(client, EMAIL_A)
    portfolio_id = await _create_portfolio(client, token)

    resp = await client.post(
        f"/api/portfolios/{portfolio_id}/holdings",
        json={"asset_id": str(uuid.uuid4()), "quantity": "1"},
        headers=_auth(token),
    )

    assert resp.status_code == 422


async def test_create_holding_avg_cost_without_currency_is_422(
    client: AsyncClient, temp_assets: TempAssets
) -> None:
    token = await _register_and_login(client, EMAIL_A)
    portfolio_id = await _create_portfolio(client, token)

    resp = await client.post(
        f"/api/portfolios/{portfolio_id}/holdings",
        json={"asset_id": str(temp_assets.pln_asset.id), "quantity": "1", "avg_cost": "10"},
        headers=_auth(token),
    )

    assert resp.status_code == 422


async def test_create_holding_on_foreign_portfolio_is_404(
    client: AsyncClient, temp_assets: TempAssets
) -> None:
    token_a = await _register_and_login(client, EMAIL_A)
    token_b = await _register_and_login(client, EMAIL_B)
    portfolio_id = await _create_portfolio(client, token_a)

    resp = await client.post(
        f"/api/portfolios/{portfolio_id}/holdings",
        json={"asset_id": str(temp_assets.pln_asset.id), "quantity": "1"},
        headers=_auth(token_b),
    )

    assert resp.status_code == 404


async def test_list_holdings_happy_path(client: AsyncClient, temp_assets: TempAssets) -> None:
    token = await _register_and_login(client, EMAIL_A)
    portfolio_id = await _create_portfolio(client, token)
    await client.post(
        f"/api/portfolios/{portfolio_id}/holdings",
        json={"asset_id": str(temp_assets.pln_asset.id), "quantity": "10"},
        headers=_auth(token),
    )
    await client.post(
        f"/api/portfolios/{portfolio_id}/holdings",
        json={"asset_id": str(temp_assets.usd_asset.id), "quantity": "2"},
        headers=_auth(token),
    )

    resp = await client.get(f"/api/portfolios/{portfolio_id}/holdings", headers=_auth(token))

    assert resp.status_code == 200
    rows = resp.json()
    assert len(rows) == 2
    total = sum(Decimal(r["value_pln"]) for r in rows)
    assert total == Decimal("500") + Decimal("800")  # 10×50 + 2×100×4


async def test_list_holdings_on_foreign_portfolio_is_404(client: AsyncClient) -> None:
    token_a = await _register_and_login(client, EMAIL_A)
    token_b = await _register_and_login(client, EMAIL_B)
    portfolio_id = await _create_portfolio(client, token_a)

    resp = await client.get(f"/api/portfolios/{portfolio_id}/holdings", headers=_auth(token_b))

    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# PATCH/DELETE /holdings/{holding_id}
# ---------------------------------------------------------------------------


async def test_update_holding_quantity_happy_path(
    client: AsyncClient, temp_assets: TempAssets
) -> None:
    token = await _register_and_login(client, EMAIL_A)
    portfolio_id = await _create_portfolio(client, token)
    create_resp = await client.post(
        f"/api/portfolios/{portfolio_id}/holdings",
        json={"asset_id": str(temp_assets.pln_asset.id), "quantity": "10"},
        headers=_auth(token),
    )
    holding_id = create_resp.json()["id"]

    resp = await client.patch(
        f"/api/holdings/{holding_id}", json={"quantity": "20"}, headers=_auth(token)
    )

    assert resp.status_code == 200
    body = resp.json()
    assert Decimal(body["quantity"]) == Decimal("20")
    assert Decimal(body["value_pln"]) == Decimal("1000")  # 20 × 50


async def test_update_holding_can_clear_avg_cost(
    client: AsyncClient, temp_assets: TempAssets
) -> None:
    token = await _register_and_login(client, EMAIL_A)
    portfolio_id = await _create_portfolio(client, token)
    create_resp = await client.post(
        f"/api/portfolios/{portfolio_id}/holdings",
        json={
            "asset_id": str(temp_assets.usd_asset.id),
            "quantity": "1",
            "avg_cost": "50",
            "cost_currency": "USD",
        },
        headers=_auth(token),
    )
    holding_id = create_resp.json()["id"]
    assert create_resp.json()["unrealized_pl"] is not None

    resp = await client.patch(
        f"/api/holdings/{holding_id}", json={"avg_cost": None}, headers=_auth(token)
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["avg_cost"] is None
    assert body["unrealized_pl"] is None


async def test_update_holding_bumps_portfolio_holdings_version(
    client: AsyncClient, temp_assets: TempAssets
) -> None:
    token = await _register_and_login(client, EMAIL_A)
    portfolio_id = await _create_portfolio(client, token)
    create_resp = await client.post(
        f"/api/portfolios/{portfolio_id}/holdings",
        json={"asset_id": str(temp_assets.pln_asset.id), "quantity": "1"},
        headers=_auth(token),
    )
    holding_id = create_resp.json()["id"]

    version_after_create = (
        await client.get(f"/api/portfolios/{portfolio_id}", headers=_auth(token))
    ).json()["holdings_version"]

    await client.patch(f"/api/holdings/{holding_id}", json={"quantity": "2"}, headers=_auth(token))

    version_after_update = (
        await client.get(f"/api/portfolios/{portfolio_id}", headers=_auth(token))
    ).json()["holdings_version"]
    assert version_after_update == version_after_create + 1


async def test_update_holding_empty_body_does_not_bump_holdings_version(
    client: AsyncClient, temp_assets: TempAssets
) -> None:
    """`PATCH {}` (żadne pole) to no-op — nie bumpuje `holdings_version`/
    `holdings_changed_at` (code-review etapu 5: bez tego guardu każdy no-op
    PATCH fałszywie oznaczał dzień jako „zmiana składu" dla joba snapshotów,
    patrz `service.update_holding`)."""
    token = await _register_and_login(client, EMAIL_A)
    portfolio_id = await _create_portfolio(client, token)
    create_resp = await client.post(
        f"/api/portfolios/{portfolio_id}/holdings",
        json={"asset_id": str(temp_assets.pln_asset.id), "quantity": "1"},
        headers=_auth(token),
    )
    holding_id = create_resp.json()["id"]

    version_after_create = (
        await client.get(f"/api/portfolios/{portfolio_id}", headers=_auth(token))
    ).json()["holdings_version"]

    resp = await client.patch(f"/api/holdings/{holding_id}", json={}, headers=_auth(token))
    assert resp.status_code == 200

    version_after_noop_patch = (
        await client.get(f"/api/portfolios/{portfolio_id}", headers=_auth(token))
    ).json()["holdings_version"]
    assert version_after_noop_patch == version_after_create


async def test_update_holding_explicit_null_quantity_is_422(
    client: AsyncClient, temp_assets: TempAssets
) -> None:
    """`quantity` to kolumna `NOT NULL` — jawny `null` w PATCH jest błędem
    klienta (422), nie cichym pominięciem (code-review etapu 5)."""
    token = await _register_and_login(client, EMAIL_A)
    portfolio_id = await _create_portfolio(client, token)
    create_resp = await client.post(
        f"/api/portfolios/{portfolio_id}/holdings",
        json={"asset_id": str(temp_assets.pln_asset.id), "quantity": "1"},
        headers=_auth(token),
    )
    holding_id = create_resp.json()["id"]

    resp = await client.patch(
        f"/api/holdings/{holding_id}", json={"quantity": None}, headers=_auth(token)
    )
    assert resp.status_code == 422


async def test_update_holding_of_other_user_is_404(
    client: AsyncClient, temp_assets: TempAssets
) -> None:
    token_a = await _register_and_login(client, EMAIL_A)
    token_b = await _register_and_login(client, EMAIL_B)
    portfolio_id = await _create_portfolio(client, token_a)
    create_resp = await client.post(
        f"/api/portfolios/{portfolio_id}/holdings",
        json={"asset_id": str(temp_assets.pln_asset.id), "quantity": "1"},
        headers=_auth(token_a),
    )
    holding_id = create_resp.json()["id"]

    resp = await client.patch(
        f"/api/holdings/{holding_id}", json={"quantity": "999"}, headers=_auth(token_b)
    )

    assert resp.status_code == 404


async def test_delete_holding_happy_path(client: AsyncClient, temp_assets: TempAssets) -> None:
    token = await _register_and_login(client, EMAIL_A)
    portfolio_id = await _create_portfolio(client, token)
    create_resp = await client.post(
        f"/api/portfolios/{portfolio_id}/holdings",
        json={"asset_id": str(temp_assets.pln_asset.id), "quantity": "1"},
        headers=_auth(token),
    )
    holding_id = create_resp.json()["id"]

    resp = await client.delete(f"/api/holdings/{holding_id}", headers=_auth(token))
    assert resp.status_code == 204

    list_resp = await client.get(f"/api/portfolios/{portfolio_id}/holdings", headers=_auth(token))
    assert list_resp.json() == []


async def test_delete_holding_of_other_user_is_404(
    client: AsyncClient, temp_assets: TempAssets
) -> None:
    token_a = await _register_and_login(client, EMAIL_A)
    token_b = await _register_and_login(client, EMAIL_B)
    portfolio_id = await _create_portfolio(client, token_a)
    create_resp = await client.post(
        f"/api/portfolios/{portfolio_id}/holdings",
        json={"asset_id": str(temp_assets.pln_asset.id), "quantity": "1"},
        headers=_auth(token_a),
    )
    holding_id = create_resp.json()["id"]

    resp = await client.delete(f"/api/holdings/{holding_id}", headers=_auth(token_b))

    assert resp.status_code == 404
    still_there = await client.get(
        f"/api/portfolios/{portfolio_id}/holdings", headers=_auth(token_a)
    )
    assert len(still_there.json()) == 1


# ---------------------------------------------------------------------------
# GET /portfolios/{id}/summary
# ---------------------------------------------------------------------------


async def test_summary_empty_portfolio(client: AsyncClient) -> None:
    token = await _register_and_login(client, EMAIL_A)
    portfolio_id = await _create_portfolio(client, token)

    resp = await client.get(f"/api/portfolios/{portfolio_id}/summary", headers=_auth(token))

    assert resp.status_code == 200
    body = resp.json()
    assert Decimal(body["value_pln"]) == Decimal("0")
    assert body["change_1d"] is None
    assert body["change_ytd"] is None
    assert body["stale_assets"] == 0
    assert body["as_of"] == today().isoformat()
    assert "markets" not in body  # decyzja #3 — ranking rynków to krok 29/30


async def test_summary_with_history_computes_change_1d_and_ytd(
    client: AsyncClient, db_session: AsyncSession, temp_assets: TempAssets
) -> None:
    token = await _register_and_login(client, EMAIL_A)
    portfolio_id = await _create_portfolio(client, token)
    await client.post(
        f"/api/portfolios/{portfolio_id}/holdings",
        json={"asset_id": str(temp_assets.pln_asset.id), "quantity": "3"},
        headers=_auth(token),
    )
    # value_pln live = 3 × 50 = 150

    d = today()
    db_session.add_all(
        [
            PortfolioValuation(
                portfolio_id=uuid.UUID(portfolio_id),
                date=d - timedelta(days=1),
                value_pln=Decimal("100"),
                composition_change=False,
            ),
            PortfolioValuation(
                portfolio_id=uuid.UUID(portfolio_id),
                date=d.replace(month=1, day=1),
                value_pln=Decimal("50"),
                composition_change=False,
            ),
        ]
    )
    await db_session.commit()

    resp = await client.get(f"/api/portfolios/{portfolio_id}/summary", headers=_auth(token))

    assert resp.status_code == 200
    body = resp.json()
    assert Decimal(body["value_pln"]) == Decimal("150")
    assert Decimal(body["change_1d"]["abs"]) == Decimal("50")
    assert Decimal(body["change_1d"]["pct"]) == Decimal("0.5")
    assert Decimal(body["change_ytd"]["abs"]) == Decimal("100")
    assert Decimal(body["change_ytd"]["pct"]) == Decimal("2")


async def test_summary_of_other_user_is_404(client: AsyncClient) -> None:
    token_a = await _register_and_login(client, EMAIL_A)
    token_b = await _register_and_login(client, EMAIL_B)
    portfolio_id = await _create_portfolio(client, token_a)

    resp = await client.get(f"/api/portfolios/{portfolio_id}/summary", headers=_auth(token_b))

    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /portfolios/{id}/valuations
# ---------------------------------------------------------------------------


async def test_valuations_empty_history_returns_empty_list(client: AsyncClient) -> None:
    token = await _register_and_login(client, EMAIL_A)
    portfolio_id = await _create_portfolio(client, token)

    resp = await client.get(f"/api/portfolios/{portfolio_id}/valuations", headers=_auth(token))

    assert resp.status_code == 200
    assert resp.json() == []


async def test_valuations_returns_ascending_and_filters_by_range(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    token = await _register_and_login(client, EMAIL_A)
    portfolio_id = await _create_portfolio(client, token)
    d = today()

    db_session.add_all(
        [
            PortfolioValuation(
                portfolio_id=uuid.UUID(portfolio_id),
                date=d - timedelta(days=400),
                value_pln=Decimal("10"),
                composition_change=False,
            ),
            PortfolioValuation(
                portfolio_id=uuid.UUID(portfolio_id),
                date=d - timedelta(days=10),
                value_pln=Decimal("20"),
                composition_change=False,
            ),
            PortfolioValuation(
                portfolio_id=uuid.UUID(portfolio_id),
                date=d,
                value_pln=Decimal("30"),
                composition_change=True,
            ),
        ]
    )
    await db_session.commit()

    resp_max = await client.get(
        f"/api/portfolios/{portfolio_id}/valuations", params={"range": "max"}, headers=_auth(token)
    )
    assert resp_max.status_code == 200
    rows_max = resp_max.json()
    assert len(rows_max) == 3
    assert [r["date"] for r in rows_max] == sorted(r["date"] for r in rows_max)

    resp_1m = await client.get(
        f"/api/portfolios/{portfolio_id}/valuations", params={"range": "1M"}, headers=_auth(token)
    )
    assert resp_1m.status_code == 200
    rows_1m = resp_1m.json()
    assert len(rows_1m) == 2  # wyklucza snapshot sprzed 400 dni
    assert Decimal(rows_1m[-1]["value_pln"]) == Decimal("30")
    assert rows_1m[-1]["composition_change"] is True


async def test_valuations_rejects_unknown_range(client: AsyncClient) -> None:
    token = await _register_and_login(client, EMAIL_A)
    portfolio_id = await _create_portfolio(client, token)

    resp = await client.get(
        f"/api/portfolios/{portfolio_id}/valuations",
        params={"range": "nope"},
        headers=_auth(token),
    )

    assert resp.status_code == 422


async def test_valuations_of_other_user_is_404(client: AsyncClient) -> None:
    token_a = await _register_and_login(client, EMAIL_A)
    token_b = await _register_and_login(client, EMAIL_B)
    portfolio_id = await _create_portfolio(client, token_a)

    resp = await client.get(f"/api/portfolios/{portfolio_id}/valuations", headers=_auth(token_b))

    assert resp.status_code == 404
