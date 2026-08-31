"""Import CSV listy pozycji — `POST /portfolios/{id}/holdings/import`
(plan krok 48, etap 9).

Integracyjne, prawdziwa baza. Aktywa tymczasowe jak w `test_holdings.py`
(`XTS` jako waluta obca — kod ISO 4217 zarezerwowany na testy, nie `USD`,
którego kurs zaciąga worker EOD). Kursu XTS ten plik **nie** zakłada: nie
sprawdza wycen, a wspólny wiersz `fx_rates` sprzęgałby go z
`test_holdings.py` przez globalny stan (jeden nieudany teardown zostawia
wiersz, który wywala setup każdego następnego przebiegu).

Ten plik pilnuje trzech rzeczy, których parser sam nie zapewnia: scalania
z istniejącą pozycją (decyzja użytkownika: import **sumuje** ilości),
nietykalności bazy przy `dry_run` oraz tego, że bump `holdings_version`
idzie raz na plik, a nie raz na wiersz.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from decimal import Decimal

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.marketdata.models import Asset, Price
from app.modules.portfolio import repository as portfolio_repository
from app.modules.portfolio.models import Holding, Portfolio
from app.modules.portfolio.service import today

EMAIL = "import-a@example.com"
PASSWORD = "correct-password-1"


async def _register_and_login(client: AsyncClient, email: str) -> str:
    await client.post("/api/auth/register", json={"email": email, "password": PASSWORD})
    resp = await client.post("/api/auth/login", json={"email": email, "password": PASSWORD})
    assert resp.status_code == 200, resp.text
    token: str = resp.json()["access_token"]
    return token


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@dataclass
class ImportAssets:
    pln: Asset
    fx: Asset
    inactive: Asset


@pytest_asyncio.fixture
async def import_assets(db_session: AsyncSession) -> AsyncGenerator[ImportAssets, None]:
    """Trzy aktywa: PLN na GPW, XTS na US oraz jedno wygaszone
    (`is_active=False`) — import ma je pomijać z powodem, a nie tworzyć
    pozycję, która nigdy nie dostanie wyceny."""
    suffix = uuid.uuid4().hex[:8]
    pln = Asset(
        symbol=f"IMPP{suffix}",
        name=f"Import PLN {suffix}",
        asset_class="equity",
        market_code="GPW",
        currency="PLN",
    )
    fx = Asset(
        symbol=f"IMPU{suffix}",
        name=f"Import XTS {suffix}",
        asset_class="equity",
        market_code="US",
        currency="XTS",
    )
    inactive = Asset(
        symbol=f"IMPX{suffix}",
        name=f"Import wygaszone {suffix}",
        asset_class="equity",
        market_code="GPW",
        currency="PLN",
        is_active=False,
    )
    db_session.add_all([pln, fx, inactive])
    await db_session.commit()
    for asset in (pln, fx, inactive):
        await db_session.refresh(asset)

    d = today()
    db_session.add_all(
        [
            Price(asset_id=pln.id, date=d, close=Decimal("50"), close_adj=Decimal("50")),
            Price(asset_id=fx.id, date=d, close=Decimal("100"), close_adj=Decimal("100")),
        ]
    )
    await db_session.commit()

    # Identyfikatory zdjęte ze świeżo odświeżonych obiektów PRZED `yield`:
    # `_version` kończy transakcję sesji (`rollback`), co wygasza atrybuty
    # ORM, a sięgnięcie po nie w teardownie próbowałoby doładować je poza
    # greenletem SQLAlchemy (`MissingGreenlet`).
    ids = [pln.id, fx.id, inactive.id]

    yield ImportAssets(pln=pln, fx=fx, inactive=inactive)

    # `Holding.asset_id` nie kaskaduje z `assets` — pozycje założone przez
    # HTTP trzeba usunąć przed aktywem (ten sam powód co w `test_holdings.py`).
    await db_session.execute(delete(Holding).where(Holding.asset_id.in_(ids)))
    await db_session.execute(delete(Price).where(Price.asset_id.in_(ids)))
    await db_session.execute(delete(Asset).where(Asset.id.in_(ids)))
    await db_session.commit()


async def _portfolio(client: AsyncClient, token: str) -> str:
    resp = await client.post(
        "/api/portfolios", json={"name": "Import", "type": "standard"}, headers=_auth(token)
    )
    assert resp.status_code == 201, resp.text
    portfolio_id: str = resp.json()["id"]
    return portfolio_id


async def _import(
    client: AsyncClient, token: str, portfolio_id: str, content: str, *, dry_run: bool = False
) -> dict:
    resp = await client.post(
        f"/api/portfolios/{portfolio_id}/holdings/import",
        json={"content": content, "dry_run": dry_run},
        headers=_auth(token),
    )
    assert resp.status_code == 200, resp.text
    body: dict = resp.json()
    return body


async def test_import_tworzy_pozycje(client: AsyncClient, import_assets: ImportAssets) -> None:
    token = await _register_and_login(client, EMAIL)
    portfolio_id = await _portfolio(client, token)

    report = await _import(
        client,
        token,
        portfolio_id,
        f"{import_assets.pln.symbol};10;120.50\n{import_assets.fx.symbol};3",
    )

    assert (report["created"], report["merged"], report["skipped"]) == (2, 0, 0)

    resp = await client.get(f"/api/portfolios/{portfolio_id}/holdings", headers=_auth(token))
    by_symbol = {row["symbol"]: row for row in resp.json()}
    assert by_symbol[import_assets.pln.symbol]["quantity"] == "10.00000000"
    # Cena nabycia trafia do istniejącej kolumny `avg_cost`, a waluta bierze
    # się z `assets.currency` (cena jest w walucie notowania, nie w PLN).
    assert by_symbol[import_assets.pln.symbol]["avg_cost"] == "120.50000000"
    assert by_symbol[import_assets.pln.symbol]["cost_currency"] == "PLN"
    # Bez ceny nabycia nie ma też waluty — CHECK `avg_cost_needs_currency`
    # dopuszcza tylko taką parę.
    assert by_symbol[import_assets.fx.symbol]["avg_cost"] is None
    assert by_symbol[import_assets.fx.symbol]["cost_currency"] is None


async def test_import_sumuje_ilosc_istniejacej_pozycji(
    client: AsyncClient, import_assets: ImportAssets
) -> None:
    """Decyzja użytkownika z 2026-08-30: import dodaje do stanu, nie nadpisuje.
    10 × 100 + 30 × 200 = 7000; 7000 / 40 = 175 (średnia ważona)."""
    token = await _register_and_login(client, EMAIL)
    portfolio_id = await _portfolio(client, token)
    symbol = import_assets.pln.symbol

    await _import(client, token, portfolio_id, f"{symbol};10;100")
    report = await _import(client, token, portfolio_id, f"{symbol};30;200")

    assert (report["created"], report["merged"]) == (0, 1)
    assert "średnia ważona" in report["rows"][0]["message"]

    resp = await client.get(f"/api/portfolios/{portfolio_id}/holdings", headers=_auth(token))
    row = resp.json()[0]
    assert row["quantity"] == "40.00000000"
    assert row["avg_cost"] == "175.00000000"


async def test_scalenie_bez_ceny_czysci_avg_cost_i_mowi_o_tym(
    client: AsyncClient, import_assets: ImportAssets
) -> None:
    """Średnia z ceny znanej i nieznanej nie istnieje — `avg_cost` znika,
    ale użytkownik dowiaduje się o tym z raportu (CLAUDE.md #3.15)."""
    token = await _register_and_login(client, EMAIL)
    portfolio_id = await _portfolio(client, token)
    symbol = import_assets.pln.symbol

    await _import(client, token, portfolio_id, f"{symbol};10;100")
    report = await _import(client, token, portfolio_id, f"{symbol};5")

    assert "wyczyszczona" in report["rows"][0]["message"]
    resp = await client.get(f"/api/portfolios/{portfolio_id}/holdings", headers=_auth(token))
    row = resp.json()[0]
    assert row["quantity"] == "15.00000000"
    assert row["avg_cost"] is None
    assert row["cost_currency"] is None


async def test_dry_run_nie_dotyka_bazy(
    client: AsyncClient, import_assets: ImportAssets, db_session: AsyncSession
) -> None:
    token = await _register_and_login(client, EMAIL)
    portfolio_id = await _portfolio(client, token)
    symbol = import_assets.pln.symbol

    await _import(client, token, portfolio_id, f"{symbol};10;100")
    before = await _version(db_session, portfolio_id)

    report = await _import(client, token, portfolio_id, f"{symbol};30;200", dry_run=True)

    assert report["dry_run"] is True
    assert report["merged"] == 1  # raport identyczny jak przy zapisie
    resp = await client.get(f"/api/portfolios/{portfolio_id}/holdings", headers=_auth(token))
    assert resp.json()[0]["quantity"] == "10.00000000"
    assert await _version(db_session, portfolio_id) == before


async def test_nieznany_i_wygaszony_symbol_sa_pomijane_z_powodem(
    client: AsyncClient, import_assets: ImportAssets
) -> None:
    """Jeden zły wiersz nie unieważnia pliku — reszta wchodzi normalnie."""
    token = await _register_and_login(client, EMAIL)
    portfolio_id = await _portfolio(client, token)

    report = await _import(
        client,
        token,
        portfolio_id,
        f"NIEISTNIEJE;1;10\n{import_assets.inactive.symbol};2;20\n{import_assets.pln.symbol};3;30",
    )

    assert (report["created"], report["skipped"]) == (1, 2)
    skipped = [row for row in report["rows"] if row["status"] == "skipped"]
    assert all("Nieznany symbol" in row["message"] for row in skipped)
    # Kolejność raportu = kolejność linii pliku, żeby dało się go zestawić
    # z tym, co użytkownik ma na ekranie.
    assert [row["line"] for row in report["rows"]] == [1, 2, 3]


async def test_symbol_bez_rozroznienia_wielkosci_liter(
    client: AsyncClient, import_assets: ImportAssets
) -> None:
    token = await _register_and_login(client, EMAIL)
    portfolio_id = await _portfolio(client, token)

    report = await _import(client, token, portfolio_id, f"{import_assets.pln.symbol.lower()};7")

    assert report["created"] == 1
    # W raporcie wraca symbol kanoniczny ze słownika, nie to, co wpisał user.
    assert report["rows"][0]["symbol"] == import_assets.pln.symbol


async def test_holdings_version_bumpuje_raz_na_plik(
    client: AsyncClient, import_assets: ImportAssets, db_session: AsyncSession
) -> None:
    """Wersja cache oznacza „skład się zmienił", nie „ile pozycji" — import
    dwóch aktywów to jedna zmiana składu, nie dwie (CLAUDE.md #3.7)."""
    token = await _register_and_login(client, EMAIL)
    portfolio_id = await _portfolio(client, token)
    before = await _version(db_session, portfolio_id)

    await _import(
        client,
        token,
        portfolio_id,
        f"{import_assets.pln.symbol};1\n{import_assets.fx.symbol};2",
    )

    assert await _version(db_session, portfolio_id) == before + 1


async def test_pusty_plik_odrzucony_przez_walidacje(client: AsyncClient) -> None:
    token = await _register_and_login(client, EMAIL)
    portfolio_id = await _portfolio(client, token)

    resp = await client.post(
        f"/api/portfolios/{portfolio_id}/holdings/import",
        json={"content": ""},
        headers=_auth(token),
    )

    assert resp.status_code == 422


async def test_za_duzy_plik_odrzucony_w_calosci(
    client: AsyncClient, import_assets: ImportAssets
) -> None:
    """Limit dotyczy pliku, nie wiersza — nie ma czego raportować per wpis,
    więc leci 422 zamiast raportu z samymi pominięciami."""
    token = await _register_and_login(client, EMAIL)
    portfolio_id = await _portfolio(client, token)

    resp = await client.post(
        f"/api/portfolios/{portfolio_id}/holdings/import",
        json={"content": f"{import_assets.pln.symbol};1;1\n" * 600},
        headers=_auth(token),
    )

    assert resp.status_code == 422


async def _version(db_session: AsyncSession, portfolio_id: str) -> int:
    """Czyta `holdings_version` prosto z bazy — `db_session` idzie rolą
    właściciela (`conftest.py`), więc omija RLS i widzi portfel niezależnie
    od kontekstu użytkownika ustawianego przez API.

    `rollback()` przed odczytem zamyka transakcję sesji testowej: zapisy
    idą osobnym połączeniem (aplikacyjnym), więc bez tego czytalibyśmy
    migawkę sprzed importu i test „nie bumpuje" byłby zielony zawsze.
    """
    await db_session.rollback()
    stmt = select(Portfolio.holdings_version).where(Portfolio.id == uuid.UUID(portfolio_id))
    version: int = (await db_session.execute(stmt)).scalar_one()
    return version


async def test_kolizja_przy_zapisie_daje_409(
    client: AsyncClient, import_assets: ImportAssets, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Stan sprawdzony na początku importu może się zmienić, zanim dojdzie do
    `commit()` (drugie okno przeglądarki, dwa importy naraz). Wtedy leci
    `UNIQUE(portfolio_id, asset_id)` — kontrakt mówi 409, nie 500.

    Kolizji nie da się wywołać deterministycznie przez HTTP (wymagałaby dwóch
    żądań przeplecionych co do instrukcji), więc podstawiamy błąd bazy w
    miejscu, w którym realnie by wystąpił.
    """
    token = await _register_and_login(client, EMAIL)
    portfolio_id = await _portfolio(client, token)

    async def _boom(*args: object, **kwargs: object) -> None:
        raise IntegrityError("INSERT", {}, Exception("duplicate key"))

    monkeypatch.setattr(portfolio_repository, "apply_import", _boom)

    resp = await client.post(
        f"/api/portfolios/{portfolio_id}/holdings/import",
        json={"content": f"{import_assets.pln.symbol};1"},
        headers=_auth(token),
    )

    assert resp.status_code == 409, resp.text


async def test_symbol_na_dwoch_rynkach_jest_pomijany_z_powodem(
    client: AsyncClient, import_assets: ImportAssets, db_session: AsyncSession
) -> None:
    """`assets.symbol` nie ma UNIQUE — ten sam ticker bywa na dwóch rynkach.

    Wybranie „któregoś" aktywa dałoby pozycję w obcej walucie i na obcym
    rynku, bez śladu w raporcie (CLAUDE.md #3.15). Import ma oddać wiersz
    użytkownikowi razem z listą rynków.
    """
    token = await _register_and_login(client, EMAIL)
    portfolio_id = await _portfolio(client, token)

    twin = Asset(
        symbol=import_assets.pln.symbol,
        name=f"{import_assets.pln.name} (US)",
        asset_class="equity",
        market_code="US",
        currency="XTS",
    )
    db_session.add(twin)
    await db_session.commit()
    twin_id = twin.id
    try:
        report = await _import(client, token, portfolio_id, f"{import_assets.pln.symbol};10;100")

        assert report["created"] == 0
        assert report["skipped"] == 1
        assert "kilku rynkach" in report["rows"][0]["message"]
        assert "GPW" in report["rows"][0]["message"] and "US" in report["rows"][0]["message"]
        resp = await client.get(f"/api/portfolios/{portfolio_id}/holdings", headers=_auth(token))
        assert resp.json() == []
    finally:
        await db_session.execute(delete(Holding).where(Holding.asset_id == twin_id))
        await db_session.execute(delete(Asset).where(Asset.id == twin_id))
        await db_session.commit()


async def test_dry_run_nie_tworzy_nowych_pozycji(
    client: AsyncClient, import_assets: ImportAssets
) -> None:
    """Podgląd nowej pozycji jest równie „nieszkodliwy" jak podgląd scalenia."""
    token = await _register_and_login(client, EMAIL)
    portfolio_id = await _portfolio(client, token)

    report = await _import(
        client, token, portfolio_id, f"{import_assets.pln.symbol};10;100", dry_run=True
    )

    assert report["created"] == 1
    resp = await client.get(f"/api/portfolios/{portfolio_id}/holdings", headers=_auth(token))
    assert resp.json() == []


async def test_same_pominiecia_nie_bumpuja_wersji(
    client: AsyncClient, import_assets: ImportAssets, db_session: AsyncSession
) -> None:
    """Skład się nie zmienił, więc klucz cache ma zostać ten sam — inaczej
    plik z samymi literówkami unieważniałby całą analitykę portfela."""
    token = await _register_and_login(client, EMAIL)
    portfolio_id = await _portfolio(client, token)
    before = await _version(db_session, portfolio_id)

    report = await _import(client, token, portfolio_id, "NIEZNANY1;10;100\nNIEZNANY2;5")

    assert report["skipped"] == 2
    assert await _version(db_session, portfolio_id) == before


async def test_scalenie_przy_innej_walucie_kosztu_czysci_cene(
    client: AsyncClient, import_assets: ImportAssets, db_session: AsyncSession
) -> None:
    """Średnia ważona z dwóch walut nie ma sensu, więc `avg_cost` idzie na
    `NULL` — i raport musi powiedzieć dlaczego (CLAUDE.md #3.15)."""
    token = await _register_and_login(client, EMAIL)
    portfolio_id = await _portfolio(client, token)
    symbol = import_assets.fx.symbol

    await _import(client, token, portfolio_id, f"{symbol};10;100")
    # Ręczna podmiana waluty kosztu na inną niż `assets.currency` — z API
    # nie da się jej rozjechać, ale w bazie taki stan jest legalny
    # (CHECK pilnuje tylko „jest cena → jest waluta").
    holdings = await db_session.execute(
        select(Holding).where(Holding.portfolio_id == uuid.UUID(portfolio_id))
    )
    holding = holdings.scalars().one()
    holding.cost_currency = "PLN"
    await db_session.commit()

    report = await _import(client, token, portfolio_id, f"{symbol};10;200")

    assert report["merged"] == 1
    assert "waluty" in report["rows"][0]["message"]
    resp = await client.get(f"/api/portfolios/{portfolio_id}/holdings", headers=_auth(token))
    position = resp.json()[0]
    assert position["quantity"] == "20.00000000"
    assert position["avg_cost"] is None
