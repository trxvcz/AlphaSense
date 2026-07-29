"""Testy `/portfolios/{id}/allocation`, `/portfolios/{id}/concentration`,
`/portfolios/{id}/markets` (plan kroki 29-30, etap 6).

Integracyjne, prawdziwa baza — ten sam wzorzec co
`tests/integration/test_holdings.py`: aktywa/ceny/kursy testowe na
`market_code` już obecnych w słowniku (`GPW` PLN, `US` z walutą testową
`XTS`, `FX` bez indeksu), losowy sufiks symbolu, sprzątanie po każdym
teście. Waluta obca to `XTS` (ISO 4217, kod zarezerwowany na testy), a nie
`USD` — realny kurs `USD` zaciąga worker EOD, więc kurs testowy dałoby się
ustawić tylko warunkowo, a wtedy asercje na kwotach zależą od tego, czy
worker już zdążył. Pełne uzasadnienie w docstringu `test_holdings.py`. Logika
grupowania/HHI/wag rynku ma już pełne pokrycie w
`tests/unit/test_analytics.py` (bez bazy) — te testy sprawdzają tylko
orkiestrację: autoryzację (`get_owned_portfolio`), serializację odpowiedzi
HTTP, 422 na nieznany `by` i (dla `/markets`) doklejenie danych indeksu z
`prices`.

Sekcja „Cache Redis" na końcu pliku (plan krok 31, CLAUDE.md #3.7) testuje
warstwę cache dodaną w `analytics/service.py` wokół tych samych trzech
funkcji — celowo w tym samym pliku (te same fixture'y `analytics_assets`/
`_add_holding`), nie osobny `tests/unit/test_cache.py`: te testy potrzebują
prawdziwej bazy (portfel/pozycje) i prawdziwego Redisa (stack testowy), więc
nie są „unit" w sensie konwencji repo („bez bazy, bez mocków").
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from datetime import time, timedelta
from decimal import Decimal

import pytest
import pytest_asyncio
from httpx import AsyncClient
from redis.exceptions import ConnectionError as RedisConnectionError
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import cache as cache_module
from app.modules.marketdata.models import Asset, FxRate, Market, Price
from app.modules.portfolio import service as portfolio_service
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
    etf_us: Asset  # US/XTS, klasa "etf", sektor "Finanse" — dla approximate=true


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
        currency="XTS",
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
    # Bezwarunkowo — `XTS` należy wyłącznie do testów, nic innego go nie pisze.
    db_session.add(FxRate(currency="XTS", date=d, rate_pln=Decimal("4")))
    await db_session.commit()

    yield AnalyticsAssets(equity_pl=equity_pl, etf_us=etf_us)

    asset_ids = [equity_pl.id, etf_us.id]
    await db_session.execute(delete(Holding).where(Holding.asset_id.in_(asset_ids)))
    await db_session.execute(delete(Price).where(Price.asset_id.in_(asset_ids)))
    await db_session.execute(delete(FxRate).where(FxRate.currency == "XTS", FxRate.date == d))
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


# ---------------------------------------------------------------------------
# GET /portfolios/{id}/markets  (krok 30, ADR-102)
# ---------------------------------------------------------------------------


@dataclass
class RankingMarkets:
    """Dwa w pełni testowe rynki dla rankingu — każdy z własnym aktywem do
    trzymania w portfelu i własnym indeksem referencyjnym."""

    with_prices_code: str
    with_prices_holding: Asset  # PLN, wyceniany
    with_prices_index: Asset  # indeks Z serią notowań
    without_prices_code: str
    without_prices_holding: Asset  # PLN, wyceniany
    without_prices_index: Asset  # indeks BEZ ani jednego wiersza `prices`


@pytest_asyncio.fixture
async def ranking_markets(db_session: AsyncSession) -> AsyncGenerator[RankingMarkets, None]:
    """Dwa tymczasowe rynki (własne `markets.code`), nie podmiana pola w
    rynku seedowym.

    Poprzednia wersja tego fixture'a (`gpw_temp_index`) na czas testu
    nadpisywała `Market("GPW").index_asset_id` i przywracała po nim —
    mutacja WSPÓŁDZIELONEGO wiersza słownika, która blokowała zrównoleglenie
    testów (drugi test czytający `GPW` w tym samym momencie zobaczyłby
    testowy indeks) i zostawiała bazę w złym stanie po przerwanym przebiegu.
    Własny `market_code` jest tak samo tani, a nie dotyka niczyich danych.

    Drugi rynek ma indeks **bez notowań** — dzięki temu przypadek
    „`index: null`, bo worker nie zaciągnął jeszcze ceny" jest wywołany
    warunkiem, który ustawia test, a nie stanem bazy. Wcześniej sprawdzano
    go na rynku `US` (`^GSPC` z seeda), więc test przechodził wyłącznie
    dopóki worker EOD nie zaciągnął S&P 500 — i padłby przy poprawnym
    kodzie w dniu pierwszej udanej ingestii."""
    suffix = uuid.uuid4().hex[:8].upper()
    with_code = f"TSTA{suffix[:4]}"
    without_code = f"TSTB{suffix[:4]}"

    db_session.add_all(
        [
            Market(
                code=with_code,
                name="Testowy rynek z indeksem",
                timezone="UTC",
                eod_time=time(18, 0),
            ),
            Market(
                code=without_code,
                name="Testowy rynek z pustym indeksem",
                timezone="UTC",
                eod_time=time(18, 0),
            ),
        ]
    )
    await db_session.commit()

    assets = {
        "with_holding": Asset(
            symbol=f"RKA{suffix}",
            name="Pozycja na rynku z indeksem",
            asset_class="equity",
            market_code=with_code,
            currency="PLN",
        ),
        "with_index": Asset(
            symbol=f"RKAI{suffix}",
            name="Indeks rynku z notowaniami",
            asset_class="index",
            market_code=with_code,
            currency="PLN",
        ),
        "without_holding": Asset(
            symbol=f"RKB{suffix}",
            name="Pozycja na rynku z pustym indeksem",
            asset_class="equity",
            market_code=without_code,
            currency="PLN",
        ),
        "without_index": Asset(
            symbol=f"RKBI{suffix}",
            name="Indeks bez notowań",
            asset_class="index",
            market_code=without_code,
            currency="PLN",
        ),
    }
    db_session.add_all(list(assets.values()))
    await db_session.commit()
    for asset in assets.values():
        await db_session.refresh(asset)

    with_market = await db_session.get(Market, with_code)
    without_market = await db_session.get(Market, without_code)
    assert with_market is not None and without_market is not None
    with_market.index_asset_id = assets["with_index"].id
    without_market.index_asset_id = assets["without_index"].id

    d = today()
    db_session.add_all(
        [
            # Wagi rankingu: 500 PLN vs 400 PLN → rynek z indeksem pierwszy.
            Price(
                asset_id=assets["with_holding"].id,
                date=d,
                close=Decimal("50"),
                close_adj=Decimal("50"),
            ),
            Price(
                asset_id=assets["without_holding"].id,
                date=d,
                close=Decimal("100"),
                close_adj=Decimal("100"),
            ),
        ]
    )
    await db_session.commit()

    yield RankingMarkets(
        with_prices_code=with_code,
        with_prices_holding=assets["with_holding"],
        with_prices_index=assets["with_index"],
        without_prices_code=without_code,
        without_prices_holding=assets["without_holding"],
        without_prices_index=assets["without_index"],
    )

    asset_ids = [a.id for a in assets.values()]
    # Kolejność sprzątania wymuszona przez FK: najpierw pozycje/ceny, potem
    # zerwanie `markets.index_asset_id -> assets.id`, dopiero na końcu aktywa.
    await db_session.execute(delete(Holding).where(Holding.asset_id.in_(asset_ids)))
    await db_session.execute(delete(Price).where(Price.asset_id.in_(asset_ids)))
    with_market.index_asset_id = None
    without_market.index_asset_id = None
    await db_session.commit()
    await db_session.execute(delete(Asset).where(Asset.id.in_(asset_ids)))
    await db_session.execute(delete(Market).where(Market.code.in_([with_code, without_code])))
    await db_session.commit()


@pytest_asyncio.fixture
async def fx_asset(db_session: AsyncSession) -> AsyncGenerator[Asset, None]:
    """Aktywo na rynku `FX` — w seedzie (`docs/slownik-rynkow.md`) `FX` nie
    ma żadnych `assets` (kursy walut nie są wyceniane jak zwykłe pozycje,
    patrz `marketdata/repository.list_fx_currencies`), ale nic w modelu nie
    zabrania przypisania aktywa do tego `market_code` — używane tu wyłącznie
    do zbadania zachowania rankingu dla rynku **bez** `index_asset_id`
    (`FX.index_asset_id is None` w słowniku, patrz `app/db/seed.py`)."""
    suffix = uuid.uuid4().hex[:8]
    asset = Asset(
        symbol=f"FXT{suffix}",
        name=f"Testowe aktywo FX {suffix}",
        asset_class="etf",
        market_code="FX",
        currency="PLN",
    )
    db_session.add(asset)
    await db_session.commit()
    await db_session.refresh(asset)

    yield asset

    await db_session.execute(delete(Holding).where(Holding.asset_id == asset.id))
    await db_session.execute(delete(Price).where(Price.asset_id == asset.id))
    await db_session.execute(delete(Asset).where(Asset.id == asset.id))
    await db_session.commit()


async def test_market_ranking_happy_path_with_index(
    client: AsyncClient,
    db_session: AsyncSession,
    ranking_markets: RankingMarkets,
) -> None:
    token = await _register_and_login(client, EMAIL_A)
    portfolio_id = await _create_portfolio(client, token)
    await _add_holding(
        client, token, portfolio_id, ranking_markets.with_prices_holding.id, "10"
    )  # 500 PLN
    await _add_holding(
        client, token, portfolio_id, ranking_markets.without_prices_holding.id, "4"
    )  # 400 PLN

    d = today()
    yesterday = d - timedelta(days=1)
    db_session.add_all(
        [
            Price(
                asset_id=ranking_markets.with_prices_index.id,
                date=yesterday,
                close_adj=Decimal("2000"),
            ),
            Price(asset_id=ranking_markets.with_prices_index.id, date=d, close_adj=Decimal("2100")),
        ]
    )
    await db_session.commit()

    resp = await client.get(f"/api/portfolios/{portfolio_id}/markets", headers=_auth(token))

    assert resp.status_code == 200
    body = resp.json()
    # 500/900 vs 400/900 -> rynek z indeksem sortowany pierwszy (malejąco po weight)
    assert [item["market_code"] for item in body] == [
        ranking_markets.with_prices_code,
        ranking_markets.without_prices_code,
    ]
    assert sum(Decimal(item["weight"]) for item in body) == Decimal("1")

    first = body[0]
    assert first["index"] is not None
    assert first["index"]["asset_id"] == str(ranking_markets.with_prices_index.id)
    assert first["index"]["symbol"] == ranking_markets.with_prices_index.symbol
    assert Decimal(first["index"]["value"]) == Decimal("2100.00000000")
    assert Decimal(first["index"]["change_1d"]["abs"]) == Decimal("100.00000000")
    assert Decimal(first["index"]["change_1d"]["pct"]) == Decimal("0.0500")
    assert first["index"]["as_of"] == d.isoformat()
    assert [p["date"] for p in first["index"]["series_30d"]] == [
        yesterday.isoformat(),
        d.isoformat(),
    ]

    # Drugi rynek MA `index_asset_id`, ale jego aktywo nie ma ani jednego
    # wiersza w `prices` -> `index: null` (nie błąd, patrz decyzje
    # service.py: „rynek z indeksem, ale bez jeszcze żadnej ceny").
    # Warunek ustawia fixture, więc asercja nie zależy od tego, co worker
    # EOD zdążył zaciągnąć do bazy deweloperskiej.
    second = body[1]
    assert second["index"] is None


async def test_market_ranking_market_without_index_shows_weight_only(
    client: AsyncClient, db_session: AsyncSession, fx_asset: Asset
) -> None:
    token = await _register_and_login(client, EMAIL_A)
    portfolio_id = await _create_portfolio(client, token)
    d = today()
    db_session.add(
        Price(asset_id=fx_asset.id, date=d, close=Decimal("10"), close_adj=Decimal("10"))
    )
    await db_session.commit()
    await _add_holding(client, token, portfolio_id, fx_asset.id, "5")

    resp = await client.get(f"/api/portfolios/{portfolio_id}/markets", headers=_auth(token))

    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["market_code"] == "FX"
    assert Decimal(body[0]["weight"]) == Decimal("1")
    assert body[0]["index"] is None


async def test_market_ranking_empty_portfolio_returns_empty_list(client: AsyncClient) -> None:
    token = await _register_and_login(client, EMAIL_A)
    portfolio_id = await _create_portfolio(client, token)

    resp = await client.get(f"/api/portfolios/{portfolio_id}/markets", headers=_auth(token))

    assert resp.status_code == 200
    assert resp.json() == []


async def test_market_ranking_of_other_user_is_404(client: AsyncClient) -> None:
    token_a = await _register_and_login(client, EMAIL_A)
    token_b = await _register_and_login(client, EMAIL_B)
    portfolio_id = await _create_portfolio(client, token_a)

    resp = await client.get(f"/api/portfolios/{portfolio_id}/markets", headers=_auth(token_b))

    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Cache Redis (plan krok 31, CLAUDE.md #3.7) — allocation/concentration/
# markets owinięte kluczem wersjonowanym `{zasob}:{portfolio_id}:...:
# {holdings_version}:{eod_marker}`. Test „Redis niedostępny" jest pierwszy
# (instrukcja zadania) — to najważniejsza gwarancja: awaria Redisa nigdy nie
# może zwrócić 500, tylko wolniejszą, ale poprawną odpowiedź.
# ---------------------------------------------------------------------------


class _BrokenRedis:
    """Podwójny Redisa, który udaje niedostępne połączenie na każdą
    operację — symuluje awarię sieci/serwera Redis (nie błąd programisty),
    dokładnie to, co `core/cache.py` musi łapać i degradować do no-op."""

    async def get(self, key: str) -> str | None:
        raise RedisConnectionError("connection refused (test)")

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        raise RedisConnectionError("connection refused (test)")


async def test_allocation_survives_redis_outage(
    client: AsyncClient, analytics_assets: AnalyticsAssets, monkeypatch: pytest.MonkeyPatch
) -> None:
    """CLAUDE.md #3.7: „Redis można w każdej chwili wyczyścić i aplikacja
    musi działać" (wolniej, nie: błąd) — z Redisem, który rzuca
    `ConnectionError` na `GET`/`SET`, endpoint nadal odpowiada `200` z
    poprawnie policzoną alokacją, nie `500`."""
    monkeypatch.setattr(cache_module, "get_redis", lambda: _BrokenRedis())

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
    total_weight = sum(Decimal(b["weight"]) for b in body["buckets"])
    assert total_weight == Decimal("1")
    by_key = {b["key"]: b for b in body["buckets"]}
    assert Decimal(by_key["equity"]["value_pln"]) == Decimal("500.00000000")
    assert Decimal(by_key["etf"]["value_pln"]) == Decimal("400.00000000")


async def test_concentration_survives_redis_outage(
    client: AsyncClient, analytics_assets: AnalyticsAssets, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cache_module, "get_redis", lambda: _BrokenRedis())

    token = await _register_and_login(client, EMAIL_A)
    portfolio_id = await _create_portfolio(client, token)
    await _add_holding(client, token, portfolio_id, analytics_assets.equity_pl.id, "10")

    resp = await client.get(f"/api/portfolios/{portfolio_id}/concentration", headers=_auth(token))

    assert resp.status_code == 200
    assert resp.json()["count"] == 1


async def test_market_ranking_survives_redis_outage(
    client: AsyncClient, analytics_assets: AnalyticsAssets, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cache_module, "get_redis", lambda: _BrokenRedis())

    token = await _register_and_login(client, EMAIL_A)
    portfolio_id = await _create_portfolio(client, token)
    await _add_holding(client, token, portfolio_id, analytics_assets.equity_pl.id, "10")

    resp = await client.get(f"/api/portfolios/{portfolio_id}/markets", headers=_auth(token))

    assert resp.status_code == 200
    assert [item["market_code"] for item in resp.json()] == ["GPW"]


async def test_allocation_second_request_hits_cache(
    client: AsyncClient, analytics_assets: AnalyticsAssets, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Drugie żądanie o ten sam stan portfela (sam `by`, sam
    `holdings_version`, sam `eod_marker`) nie woła ponownie
    `portfolio_service.current_value` — dowód, że trafiło w cache, nie
    liczy się na żywo (skill `fastapi-modul`: „Cache")."""
    calls = 0
    original_current_value = portfolio_service.current_value

    async def _counting_current_value(db: object, portfolio: object, on_date: object) -> object:
        nonlocal calls
        calls += 1
        return await original_current_value(db, portfolio, on_date)  # type: ignore[arg-type]

    monkeypatch.setattr(portfolio_service, "current_value", _counting_current_value)

    token = await _register_and_login(client, EMAIL_A)
    portfolio_id = await _create_portfolio(client, token)
    await _add_holding(client, token, portfolio_id, analytics_assets.equity_pl.id, "10")

    resp1 = await client.get(
        f"/api/portfolios/{portfolio_id}/allocation",
        params={"by": "class"},
        headers=_auth(token),
    )
    resp2 = await client.get(
        f"/api/portfolios/{portfolio_id}/allocation",
        params={"by": "class"},
        headers=_auth(token),
    )

    assert resp1.status_code == 200
    assert resp2.status_code == 200
    assert resp1.json() == resp2.json()
    assert calls == 1  # drugie żądanie obsłużone z cache, bez ponownej wyceny


async def test_allocation_cache_key_separates_dimensions(
    client: AsyncClient, analytics_assets: AnalyticsAssets, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Segment `by` realnie rozdziela klucz cache — dwa wymiary tego samego
    portfela to dwa wpisy, nie jeden.

    Bez tego testu usunięcie `by` z `cache_key(...)` w `analytics/service.py`
    nie zapaliłoby niczego w suicie, a użytkownik dostałby alokację
    policzoną po INNYM wymiarze niż zamówił — cicho i wiarygodnie wyglądając
    (te same wagi, tylko nie te koszyki). Stąd asercja na obu rzeczach naraz:
    na ponownym policzeniu (`calls == 2`) i na tym, że drugie żądanie wróciło
    z kluczami sektorów, nie klas."""
    calls = 0
    original_current_value = portfolio_service.current_value

    async def _counting_current_value(db: object, portfolio: object, on_date: object) -> object:
        nonlocal calls
        calls += 1
        return await original_current_value(db, portfolio, on_date)  # type: ignore[arg-type]

    monkeypatch.setattr(portfolio_service, "current_value", _counting_current_value)

    token = await _register_and_login(client, EMAIL_A)
    portfolio_id = await _create_portfolio(client, token)
    await _add_holding(client, token, portfolio_id, analytics_assets.equity_pl.id, "10")  # 500 PLN
    await _add_holding(client, token, portfolio_id, analytics_assets.etf_us.id, "1")  # 400 PLN

    by_class = await client.get(
        f"/api/portfolios/{portfolio_id}/allocation",
        params={"by": "class"},
        headers=_auth(token),
    )
    by_sector = await client.get(
        f"/api/portfolios/{portfolio_id}/allocation",
        params={"by": "sector"},
        headers=_auth(token),
    )

    assert by_class.status_code == 200
    assert by_sector.status_code == 200
    assert calls == 2  # drugi wymiar policzony od nowa, nie podany z cache pierwszego
    assert by_class.json()["by"] == "class"
    assert by_sector.json()["by"] == "sector"
    assert {b["key"] for b in by_class.json()["buckets"]} == {"equity", "etf"}
    assert {b["key"] for b in by_sector.json()["buckets"]} == {"Technologia", "Finanse"}


async def test_allocation_cache_invalidated_by_holdings_version_change(
    client: AsyncClient, analytics_assets: AnalyticsAssets, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Zmiana składu portfela (PATCH na pozycję → bump `holdings_version`,
    `portfolio/service.py::update_holding`) zmienia klucz cache — drugie
    żądanie po zmianie musi policzyć się od nowa i zwrócić świeżą wartość,
    nie starą z cache."""
    calls = 0
    original_current_value = portfolio_service.current_value

    async def _counting_current_value(db: object, portfolio: object, on_date: object) -> object:
        nonlocal calls
        calls += 1
        return await original_current_value(db, portfolio, on_date)  # type: ignore[arg-type]

    monkeypatch.setattr(portfolio_service, "current_value", _counting_current_value)

    token = await _register_and_login(client, EMAIL_A)
    portfolio_id = await _create_portfolio(client, token)
    create_resp = await client.post(
        f"/api/portfolios/{portfolio_id}/holdings",
        json={"asset_id": str(analytics_assets.equity_pl.id), "quantity": "10"},  # 500 PLN
        headers=_auth(token),
    )
    assert create_resp.status_code == 201, create_resp.text
    holding_id = create_resp.json()["id"]

    resp1 = await client.get(f"/api/portfolios/{portfolio_id}/concentration", headers=_auth(token))
    assert resp1.status_code == 200
    assert resp1.json()["count"] == 1

    patch_resp = await client.patch(
        f"/api/holdings/{holding_id}", json={"quantity": "20"}, headers=_auth(token)
    )
    assert patch_resp.status_code == 200, patch_resp.text

    resp2 = await client.get(f"/api/portfolios/{portfolio_id}/concentration", headers=_auth(token))
    assert resp2.status_code == 200
    assert resp2.json()["count"] == 1  # nadal jedna pozycja, ale przeliczona na nowo

    assert calls == 2  # brak trafienia w cache po zmianie holdings_version
