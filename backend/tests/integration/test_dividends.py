"""Testy `GET /portfolios/{id}/dividends` (plan krok 47, etap 9).

Integracyjne, prawdziwa baza — ten sam wzorzec co
`tests/integration/test_news.py`: aktywa testowe z losowym sufiksem symbolu,
sprzątanie po każdym teście. Zdarzenia wstawiamy **przez repozytorium**,
nie przez joba: job pobiera z sieci, a te testy sprawdzają odczyt,
autoryzację i to, co ten ekran mówi o **zasięgu danych**.

Osią jest różnica, której nie widać w samych wierszach: spółka **nieobjęta**
danymi (dziś: cała GPW) i spółka objęta, ale **niepłacąca** dywidendy mają
w bazie identycznie zero zdarzeń. Kalendarz, który ich nie rozróżnia,
pokazuje polskiemu portfelowi pusty ekran znaczący „nie mamy danych",
a wyglądający na „nic Cię nie czeka" (CLAUDE.md #3.15).
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.dividends import repository
from app.modules.dividends.models import DividendEvent
from app.modules.dividends.service import DIVIDEND_PROVIDER
from app.modules.marketdata.models import Asset, AssetSourceMap, Price
from app.modules.portfolio.models import Holding
from app.modules.portfolio.service import today

EMAIL_A = "div-a@example.com"
EMAIL_B = "div-b@example.com"
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


async def _add_holding(
    client: AsyncClient, token: str, portfolio_id: str, asset_id: uuid.UUID, quantity: str = "10"
) -> None:
    resp = await client.post(
        f"/api/portfolios/{portfolio_id}/holdings",
        json={"asset_id": str(asset_id), "quantity": quantity},
        headers=_auth(token),
    )
    assert resp.status_code == 201, resp.text


@dataclass
class DividendAssets:
    covered: Asset  # ma mapowanie na dostawcę dywidend (rynek US)
    uncovered: Asset  # GPW — bez mapowania, czyli poza zasięgiem danych


@pytest_asyncio.fixture
async def dividend_assets(db_session: AsyncSession) -> AsyncGenerator[DividendAssets, None]:
    suffix = uuid.uuid4().hex[:8]
    covered = Asset(
        symbol=f"DIVA{suffix}",
        name=f"Dividend Covered {suffix}",
        asset_class="equity",
        market_code="US",
        currency="USD",
    )
    uncovered = Asset(
        symbol=f"DIVB{suffix}",
        name=f"Dividend Uncovered {suffix}",
        asset_class="equity",
        market_code="GPW",
        currency="PLN",
    )
    db_session.add_all([covered, uncovered])
    await db_session.commit()
    await db_session.refresh(covered)
    await db_session.refresh(uncovered)

    db_session.add(
        AssetSourceMap(
            asset_id=covered.id,
            provider=DIVIDEND_PROVIDER,
            provider_symbol=covered.symbol,
            priority=3,
        )
    )
    d = today()
    db_session.add_all(
        [
            Price(asset_id=covered.id, date=d, close=Decimal("50"), close_adj=Decimal("50")),
            Price(asset_id=uncovered.id, date=d, close=Decimal("50"), close_adj=Decimal("50")),
        ]
    )
    await db_session.commit()

    yield DividendAssets(covered=covered, uncovered=uncovered)

    asset_ids = [covered.id, uncovered.id]
    await db_session.execute(delete(DividendEvent).where(DividendEvent.asset_id.in_(asset_ids)))
    await db_session.execute(delete(AssetSourceMap).where(AssetSourceMap.asset_id.in_(asset_ids)))
    await db_session.execute(delete(Holding).where(Holding.asset_id.in_(asset_ids)))
    await db_session.execute(delete(Price).where(Price.asset_id.in_(asset_ids)))
    await db_session.execute(delete(Asset).where(Asset.id.in_(asset_ids)))
    await db_session.commit()


async def _insert_event(
    db: AsyncSession,
    *,
    asset_id: uuid.UUID,
    days_ahead: int,
    amount: str = "0.27",
    currency: str = "USD",
) -> None:
    ex_date = today() + timedelta(days=days_ahead)
    await repository.upsert_dividend_event(
        db,
        asset_id=asset_id,
        ex_date=ex_date,
        amount=Decimal(amount),
        currency=currency,
        source=DIVIDEND_PROVIDER,
        fetched_at=datetime.now(UTC),
        pay_date=ex_date + timedelta(days=3),
    )
    await db.commit()


async def test_kalendarz_zwraca_nadchodzace_zdarzenia_z_szacunkiem_kwoty(
    client: AsyncClient, db_session: AsyncSession, dividend_assets: DividendAssets
) -> None:
    token = await _register_and_login(client, EMAIL_A)
    portfolio_id = await _create_portfolio(client, token)
    await _add_holding(client, token, portfolio_id, dividend_assets.covered.id, quantity="10")
    await _insert_event(db_session, asset_id=dividend_assets.covered.id, days_ahead=7)

    resp = await client.get(f"/api/portfolios/{portfolio_id}/dividends", headers=_auth(token))

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["items"]) == 1
    item = body["items"][0]
    assert item["symbol"] == dividend_assets.covered.symbol
    # Kwoty jako STRING (CLAUDE.md #3.1) — nie `float`.
    assert item["amount_per_share"] == "0.27000000"
    assert item["quantity"] == "10.00000000"
    # Szacunek = kwota na akcję × ilość, w walucie zdarzenia. Bez przeliczeń
    # na PLN: kurs właściwy dla wypłaty jest z przyszłości.
    # Dokładny string, nie tylko wartość: kontrakt obiecuje skalę
    # NUMERIC(20,8), a mnożenie `Decimal` samo z siebie dałoby tu
    # "2.7000000000000000" (skale czynników się sumują).
    assert item["estimated_gross"] == "2.70000000"
    assert item["currency"] == "USD"


async def test_zdarzenie_z_przeszlosci_i_spoza_horyzontu_nie_wchodzi(
    client: AsyncClient, db_session: AsyncSession, dividend_assets: DividendAssets
) -> None:
    """Ex-data wczorajsza jest już nie do złapania, a pokazana w kalendarzu
    „nadchodzących" sugerowałaby, że da się z nią coś zrobić."""
    token = await _register_and_login(client, EMAIL_A)
    portfolio_id = await _create_portfolio(client, token)
    await _add_holding(client, token, portfolio_id, dividend_assets.covered.id)
    await _insert_event(db_session, asset_id=dividend_assets.covered.id, days_ahead=-1)
    await _insert_event(db_session, asset_id=dividend_assets.covered.id, days_ahead=120)

    resp = await client.get(
        f"/api/portfolios/{portfolio_id}/dividends?horizon_days=30", headers=_auth(token)
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["items"] == []
    assert resp.json()["horizon_days"] == 30


async def test_brak_pokrycia_jest_nazwany_a_nie_przemilczany(
    client: AsyncClient, db_session: AsyncSession, dividend_assets: DividendAssets
) -> None:
    """**Najważniejszy test tego pliku** (plan krok 47: „GPW oznaczone jako
    ograniczenie"). Portfel wyłącznie z GPW dostaje pusty kalendarz — i musi
    dostać razem z nim informację, że tego rynku nie pokrywamy, bo inaczej
    pustka znaczy „nic Cię nie czeka"."""
    token = await _register_and_login(client, EMAIL_A)
    portfolio_id = await _create_portfolio(client, token)
    await _add_holding(client, token, portfolio_id, dividend_assets.uncovered.id)

    resp = await client.get(f"/api/portfolios/{portfolio_id}/dividends", headers=_auth(token))

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["items"] == []
    assert body["assets_covered"] == 0
    assert dividend_assets.uncovered.symbol in body["assets_without_coverage"]
    assert "GPW" in body["uncovered_markets"]


async def test_rynek_z_choc_jednym_pokrytym_aktywem_nie_jest_nieobjety(
    client: AsyncClient, db_session: AsyncSession, dividend_assets: DividendAssets
) -> None:
    """„Nie pokrywamy tego rynku" ma być zdaniem prawdziwym, nie ostrożnym:
    rynek trafia na listę dopiero wtedy, gdy ŻADNE aktywo portfela z tego
    rynku nie ma pokrycia."""
    token = await _register_and_login(client, EMAIL_A)
    portfolio_id = await _create_portfolio(client, token)
    await _add_holding(client, token, portfolio_id, dividend_assets.covered.id)
    await _add_holding(client, token, portfolio_id, dividend_assets.uncovered.id)

    resp = await client.get(f"/api/portfolios/{portfolio_id}/dividends", headers=_auth(token))

    body = resp.json()
    assert body["assets_covered"] == 1
    assert "US" not in body["uncovered_markets"]
    assert "GPW" in body["uncovered_markets"]


async def test_kalendarz_cudzego_portfela_to_404(
    client: AsyncClient, db_session: AsyncSession, dividend_assets: DividendAssets
) -> None:
    """404, nie 403 — nie zdradzamy istnienia cudzego zasobu (skill
    `izolacja-danych`). Harness `tests/test_isolation.py` łapie tę trasę
    automatycznie po `portfolio_id`; ten test zostaje jako czytelny opis
    kontraktu przy samym module."""
    token_a = await _register_and_login(client, EMAIL_A)
    portfolio_a = await _create_portfolio(client, token_a)
    await _add_holding(client, token_a, portfolio_a, dividend_assets.covered.id)
    await _insert_event(db_session, asset_id=dividend_assets.covered.id, days_ahead=7)

    token_b = await _register_and_login(client, EMAIL_B)
    resp = await client.get(f"/api/portfolios/{portfolio_a}/dividends", headers=_auth(token_b))

    assert resp.status_code == 404, resp.text


async def test_korekta_zapowiedzi_nadpisuje_wiersz(
    client: AsyncClient, db_session: AsyncSession, dividend_assets: DividendAssets
) -> None:
    """Kwota zapowiedzianej dywidendy bywa korygowana przed wypłatą, więc
    świeższa odpowiedź dostawcy wygrywa (`ON CONFLICT DO UPDATE`) —
    odwrotnie niż przy newsach, gdzie treść depeszy jest niezmienna."""
    token = await _register_and_login(client, EMAIL_A)
    portfolio_id = await _create_portfolio(client, token)
    await _add_holding(client, token, portfolio_id, dividend_assets.covered.id, quantity="10")

    is_new = await repository.upsert_dividend_event(
        db_session,
        asset_id=dividend_assets.covered.id,
        ex_date=today() + timedelta(days=5),
        amount=Decimal("0.25"),
        currency="USD",
        source=DIVIDEND_PROVIDER,
        fetched_at=datetime.now(UTC),
    )
    assert is_new is True
    is_new_again = await repository.upsert_dividend_event(
        db_session,
        asset_id=dividend_assets.covered.id,
        ex_date=today() + timedelta(days=5),
        amount=Decimal("0.27"),
        currency="USD",
        source=DIVIDEND_PROVIDER,
        fetched_at=datetime.now(UTC),
    )
    assert is_new_again is False
    await db_session.commit()

    resp = await client.get(f"/api/portfolios/{portfolio_id}/dividends", headers=_auth(token))

    items = resp.json()["items"]
    assert len(items) == 1, "korekta ma NADPISAĆ zdarzenie, nie dołożyć drugie"
    assert Decimal(items[0]["amount_per_share"]) == Decimal("0.27")


async def test_ta_sama_dywidenda_dwoch_uzytkownikow_daje_wlasne_ilosci(
    client: AsyncClient, db_session: AsyncSession, dividend_assets: DividendAssets
) -> None:
    """Zdarzenie dywidendowe nie należy do użytkownika — prywatna jest
    wielkość pozycji. Ten sam wiersz `dividend_events` ma dwóm osobom
    pokazać dwa różne szacunki."""
    token_a = await _register_and_login(client, EMAIL_A)
    portfolio_a = await _create_portfolio(client, token_a)
    await _add_holding(client, token_a, portfolio_a, dividend_assets.covered.id, quantity="10")

    token_b = await _register_and_login(client, EMAIL_B)
    portfolio_b = await _create_portfolio(client, token_b)
    await _add_holding(client, token_b, portfolio_b, dividend_assets.covered.id, quantity="3")

    await _insert_event(db_session, asset_id=dividend_assets.covered.id, days_ahead=7)

    resp_a = await client.get(f"/api/portfolios/{portfolio_a}/dividends", headers=_auth(token_a))
    resp_b = await client.get(f"/api/portfolios/{portfolio_b}/dividends", headers=_auth(token_b))

    assert Decimal(resp_a.json()["items"][0]["estimated_gross"]) == Decimal("2.7")
    assert Decimal(resp_b.json()["items"][0]["estimated_gross"]) == Decimal("0.81")
