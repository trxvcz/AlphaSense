"""Testy `GET /portfolios/{id}/performance` (plan krok 40, etap 8).

Matematyka łańcucha ma pełne pokrycie w `tests/unit/test_returns.py` (bez
bazy, na znanych liczbach). Tutaj wyłącznie orkiestracja: autoryzacja
zasobowa, filtr `range`, serializacja `Decimal`→string oraz warstwa cache —
w tym jedyny przypadek, którego czysta matematyka nie może złapać:
**dopisanie historii WSTECZ musi unieważnić klucz** (`seed-history` z kroku
zerowego etapu 8 robi dokładnie to).

Endpoint czyta wyłącznie `portfolio_valuations`, więc fixture'y wstawiają
snapshoty wprost — bez aktywów, cen i kursów. `_clean_auth_tables`
z `conftest.py` kasuje `users CASCADE`, a `portfolio_valuations` wisi na
`portfolios` przez `ON DELETE CASCADE`, więc sprzątanie dzieje się samo.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal

import pytest
import pytest_asyncio
from httpx import AsyncClient
from redis.exceptions import RedisError
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import cache as cache_module
from app.modules.analytics import service as analytics_service
from app.modules.marketdata.models import Asset, FxRate, Price
from app.modules.portfolio.models import PortfolioValuation
from app.modules.portfolio.service import today

EMAIL_A = "perf-a@example.com"
EMAIL_B = "perf-b@example.com"
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


async def _create_portfolio(client: AsyncClient, token: str) -> str:
    resp = await client.post(
        "/api/portfolios", json={"name": "Wyniki", "type": "standard"}, headers=_auth(token)
    )
    assert resp.status_code == 201, resp.text
    portfolio_id: str = resp.json()["id"]
    return portfolio_id


async def _add_valuations(
    db_session: AsyncSession,
    portfolio_id: str,
    *rows: tuple[int, str] | tuple[int, str, bool],
) -> None:
    """`(dni wstecz od dziś, wartość [, composition_change])` → snapshoty.

    Liczone względem `today()`, a nie na stałych datach: `range=1M`/`1Y`
    odcina okno od dnia dzisiejszego, więc test na sztywnej dacie przestałby
    cokolwiek sprawdzać wraz z upływem czasu.
    """
    d = today()
    db_session.add_all(
        [
            PortfolioValuation(
                portfolio_id=uuid.UUID(portfolio_id),
                date=d - timedelta(days=row[0]),
                value_pln=Decimal(row[1]),
                composition_change=bool(row[2]) if len(row) > 2 else False,
            )
            for row in rows
        ]
    )
    await db_session.commit()


async def _get(client: AsyncClient, token: str, portfolio_id: str, **params: str) -> dict:
    resp = await client.get(
        f"/api/portfolios/{portfolio_id}/performance", params=params, headers=_auth(token)
    )
    assert resp.status_code == 200, resp.text
    body: dict = resp.json()
    return body


# --- ścieżka szczęśliwa ----------------------------------------------------


async def test_period_return_and_index_series(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """1000 → 1100 → 990: +10%, -10%, razem -1% (składanie, nie dodawanie)."""
    token = await _register_and_login(client, EMAIL_A)
    portfolio_id = await _create_portfolio(client, token)
    await _add_valuations(db_session, portfolio_id, (2, "1000"), (1, "1100"), (0, "990"))

    body = await _get(client, token, portfolio_id)

    assert Decimal(body["period_return"]) == Decimal("-0.01")
    assert body["links"] == 2
    assert body["skipped_composition_change"] == 0
    assert [Decimal(p["index"]) for p in body["points"]] == [
        Decimal("100"),
        Decimal("110"),
        Decimal("99"),
    ]
    assert body["points"][0]["ret"] is None, "pierwszy punkt nie ma poprzednika"


async def test_amounts_are_serialized_as_strings(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """CLAUDE.md #3.1 — kwoty i ułamki jako string, nigdy `float`."""
    token = await _register_and_login(client, EMAIL_A)
    portfolio_id = await _create_portfolio(client, token)
    await _add_valuations(db_session, portfolio_id, (1, "1000"), (0, "1100"))

    body = await _get(client, token, portfolio_id)

    assert isinstance(body["period_return"], str)
    point = body["points"][-1]
    assert isinstance(point["value_pln"], str)
    assert isinstance(point["index"], str)
    assert isinstance(point["ret"], str)


async def test_composition_change_survives_the_whole_stack(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Sedno kroku 40, sprawdzone end-to-end: dopłata nie może udawać zysku.

    1000 → 1500 (dopisana pozycja) → 1650. Wartość urosła o 65%, zwrot
    wynosi 10%, a dzień dopłaty ma `ret=null` — nie `"0"`, bo zwrotu za ten
    dzień nie znamy.
    """
    token = await _register_and_login(client, EMAIL_A)
    portfolio_id = await _create_portfolio(client, token)
    await _add_valuations(db_session, portfolio_id, (2, "1000"), (1, "1500", True), (0, "1650"))

    body = await _get(client, token, portfolio_id)

    assert Decimal(body["period_return"]) == Decimal("0.1")
    assert body["links"] == 1
    assert body["skipped_composition_change"] == 1
    assert body["points"][1]["ret"] is None
    assert Decimal(body["points"][1]["index"]) == Decimal("100"), "indeks stoi na zerwanym ogniwie"
    assert Decimal(body["points"][1]["value_pln"]) == Decimal("1500"), "wartość rośnie normalnie"


async def test_empty_history_gives_null_return_not_zero(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Portfel bez snapshotów nie ma zwrotu równego zeru — on go nie ma.
    UI musi móc odróżnić „nic nie zarobił" od „nie wiemy" (CLAUDE.md #3.15)."""
    token = await _register_and_login(client, EMAIL_A)
    portfolio_id = await _create_portfolio(client, token)

    body = await _get(client, token, portfolio_id)

    assert body["period_return"] is None
    assert body["points"] == []
    assert body["links"] == 0
    assert body["first_date"] is None


async def test_single_snapshot_has_a_point_but_no_return(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Portfel założony wczoraj: jest co narysować, nie ma czego policzyć."""
    token = await _register_and_login(client, EMAIL_A)
    portfolio_id = await _create_portfolio(client, token)
    await _add_valuations(db_session, portfolio_id, (0, "1000"))

    body = await _get(client, token, portfolio_id)

    assert body["period_return"] is None
    assert len(body["points"]) == 1
    assert Decimal(body["points"][0]["index"]) == Decimal("100")


# --- zakres ----------------------------------------------------------------


async def test_range_narrows_the_window(client: AsyncClient, db_session: AsyncSession) -> None:
    """`range=1M` liczy zwrot od punktu sprzed miesiąca, nie od początku
    historii — inaczej każdy zakres dawałby tę samą liczbę."""
    token = await _register_and_login(client, EMAIL_A)
    portfolio_id = await _create_portfolio(client, token)
    await _add_valuations(db_session, portfolio_id, (200, "500"), (10, "1000"), (0, "1100"))

    full = await _get(client, token, portfolio_id, range="max")
    month = await _get(client, token, portfolio_id, range="1M")

    assert full["links"] == 2
    assert Decimal(full["period_return"]) == Decimal("1.2")  # 500 → 1100
    assert month["links"] == 1
    assert Decimal(month["period_return"]) == Decimal("0.1")  # 1000 → 1100


async def test_unknown_range_is_422(client: AsyncClient) -> None:
    token = await _register_and_login(client, EMAIL_A)
    portfolio_id = await _create_portfolio(client, token)

    resp = await client.get(
        f"/api/portfolios/{portfolio_id}/performance",
        params={"range": "5Y"},
        headers=_auth(token),
    )

    assert resp.status_code == 422


# --- izolacja danych -------------------------------------------------------


async def test_performance_of_other_user_is_404(client: AsyncClient) -> None:
    """Nie zdradzamy istnienia cudzego portfela — 404, nie 403
    (skill `izolacja-danych`)."""
    token_a = await _register_and_login(client, EMAIL_A)
    token_b = await _register_and_login(client, EMAIL_B)
    portfolio_id = await _create_portfolio(client, token_a)

    resp = await client.get(f"/api/portfolios/{portfolio_id}/performance", headers=_auth(token_b))

    assert resp.status_code == 404


# --- cache -----------------------------------------------------------------


async def test_history_added_backwards_invalidates_the_cache(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Regresja na marker cache: `seed-history` dopisuje lata WSTECZ.

    Gdyby kluczem było samo `MAX(date)` (jak `_eod_marker` dla danych
    rynkowych, gdzie wiersze przybywają tylko od najnowszej strony), ten
    przebieg trafiłby w cache i zwrócił zwrot policzony z krótszej serii —
    błędną liczbę podaną z pełnym przekonaniem, aż do wygaśnięcia TTL.
    """
    token = await _register_and_login(client, EMAIL_A)
    portfolio_id = await _create_portfolio(client, token)
    await _add_valuations(db_session, portfolio_id, (10, "1000"), (0, "1100"))

    before = await _get(client, token, portfolio_id)
    assert Decimal(before["period_return"]) == Decimal("0.1")

    # Wiersz sprzed serii — `MAX(date)` bez zmian, `COUNT(*)` w górę.
    await _add_valuations(db_session, portfolio_id, (20, "500"))
    after = await _get(client, token, portfolio_id)

    assert after["links"] == 2
    assert Decimal(after["period_return"]) == Decimal("1.2")
    assert after["first_date"] != before["first_date"]


async def test_second_call_is_served_from_cache(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Drugie wywołanie nie może dotknąć bazy snapshotów — to jest cały sens
    warstwy cache (krok 31). Sprawdzane przez podmianę repozytorium na
    wybuchającą funkcję, nie przez pomiar czasu."""
    token = await _register_and_login(client, EMAIL_A)
    portfolio_id = await _create_portfolio(client, token)
    await _add_valuations(db_session, portfolio_id, (1, "1000"), (0, "1100"))

    first = await _get(client, token, portfolio_id)

    def _boom(*args: object, **kwargs: object) -> None:
        raise AssertionError("drugie wywołanie policzyło serię zamiast wziąć ją z cache")

    monkeypatch.setattr(analytics_service.portfolio_repository, "list_valuations", _boom)
    second = await _get(client, token, portfolio_id)

    assert second == first


class _BrokenRedis:
    """Redis, który rzuca `ConnectionError` na każdą operację. `incr`/`expire`
    są potrzebne, bo żądanie przechodzi najpierw przez limiter domyślny
    (patrz `test_analytics.py`, ta sama klasa)."""

    async def get(self, key: str) -> str | None:
        raise RedisError("connection refused (test)")

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        raise RedisError("connection refused (test)")

    async def incr(self, key: str) -> int:
        raise RedisError("connection refused (test)")

    async def expire(self, key: str, seconds: int) -> bool:
        raise RedisError("connection refused (test)")


async def test_performance_survives_redis_outage(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """CLAUDE.md #3.7 — awaria Redisa daje wolniejszą, ale poprawną
    odpowiedź, nigdy 500."""
    monkeypatch.setattr(cache_module, "get_redis", lambda: _BrokenRedis())

    token = await _register_and_login(client, EMAIL_A)
    portfolio_id = await _create_portfolio(client, token)
    await _add_valuations(db_session, portfolio_id, (1, "1000"), (0, "1100"))

    body = await _get(client, token, portfolio_id)

    assert Decimal(body["period_return"]) == Decimal("0.1")


# --- benchmark (krok 42) ---------------------------------------------------
#
# Mechanizm testowany na WŁASNYM aktywie o losowym symbolu, nie na realnym
# `ETFBW20TR`/`^GSPC` ze słownika: te dwa mają w bazie dev pełną historię
# z `make backfill` (1250 notowań), więc test dopisujący notowanie „na dziś"
# zderzałby się z prawdziwym wierszem, a test „benchmark bez notowań" nigdy
# nie zobaczyłby pustki. Mapowanie klucz → symbol jest podmieniane przez
# `monkeypatch` na `service.BENCHMARKS`; że w produkcji wskazuje ono na
# ETF-a, pilnuje osobny test bez bazy (`test_real_benchmark_mapping`).
# Waluta obca to `XTS` (kod zarezerwowany na testy) — `USD` ma realne kursy
# NBP z backfillu i nadpisywanie ich psułoby dane dev (ta sama zasada co
# w `test_analytics.py`).


@dataclass
class BenchmarkFixture:
    asset: Asset
    key: str


@pytest_asyncio.fixture
async def benchmark_pln(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> AsyncGenerator[BenchmarkFixture, None]:
    async for fixture in _benchmark_fixture(db_session, monkeypatch, "PLN", "WIG20"):
        yield fixture


@pytest_asyncio.fixture
async def benchmark_foreign(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> AsyncGenerator[BenchmarkFixture, None]:
    async for fixture in _benchmark_fixture(db_session, monkeypatch, "XTS", "^GSPC"):
        yield fixture


async def _benchmark_fixture(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, currency: str, key: str
) -> AsyncGenerator[BenchmarkFixture, None]:
    asset = Asset(
        symbol=f"BMK{uuid.uuid4().hex[:8]}",
        name="Benchmark testowy",
        asset_class="index",
        market_code="GPW" if currency == "PLN" else "US",
        currency=currency,
    )
    db_session.add(asset)
    await db_session.commit()
    await db_session.refresh(asset)

    real = analytics_service.BENCHMARKS[key]
    monkeypatch.setitem(
        analytics_service.BENCHMARKS,
        key,
        analytics_service.BenchmarkSpec(
            key=real.key,
            symbol=asset.symbol,
            label=real.label,
            approximate=real.approximate,
            note=real.note,
        ),
    )

    yield BenchmarkFixture(asset=asset, key=key)

    await db_session.execute(delete(Price).where(Price.asset_id == asset.id))
    await db_session.execute(delete(FxRate).where(FxRate.currency == "XTS"))
    await db_session.execute(delete(Asset).where(Asset.id == asset.id))
    await db_session.commit()


async def _add_quotes(db_session: AsyncSession, asset: Asset, *rows: tuple[int, str]) -> None:
    """`(dni wstecz od dziś, close_adj)` → notowania benchmarku."""
    d = today()
    db_session.add_all(
        [
            Price(
                asset_id=asset.id,
                date=d - timedelta(days=days),
                close=Decimal(value),
                close_adj=Decimal(value),
                source="test",
            )
            for days, value in rows
        ]
    )
    await db_session.commit()


async def _add_fx(db_session: AsyncSession, *rows: tuple[int, str]) -> None:
    d = today()
    db_session.add_all(
        [
            FxRate(currency="XTS", date=d - timedelta(days=days), rate_pln=Decimal(rate))
            for days, rate in rows
        ]
    )
    await db_session.commit()


def test_real_benchmark_mapping() -> None:
    """Bez bazy: to, na co wskazują klucze W PRODUKCJI. Decyzja 8 planu —
    WIG20 nie ma dostępnego źródła historii, więc liczy go ETF, a odpowiedź
    musi to ujawniać (CLAUDE.md #3.15)."""
    wig20 = analytics_service.BENCHMARKS["WIG20"]

    assert wig20.symbol == "ETFBW20TR"
    assert wig20.approximate is True
    assert wig20.note and "ETF" in wig20.note

    sp500 = analytics_service.BENCHMARKS["^GSPC"]
    assert sp500.symbol == "^GSPC"
    assert sp500.approximate is False


async def test_benchmark_series_is_normalized_to_the_portfolio_start(
    client: AsyncClient, db_session: AsyncSession, benchmark_pln: BenchmarkFixture
) -> None:
    """Obie serie startują od 100 tego samego dnia — o to chodzi w porównaniu.
    Portfel +10%, benchmark +20%: portfel przegrał z rynkiem."""
    token = await _register_and_login(client, EMAIL_A)
    portfolio_id = await _create_portfolio(client, token)
    await _add_valuations(db_session, portfolio_id, (1, "1000"), (0, "1100"))
    await _add_quotes(db_session, benchmark_pln.asset, (1, "200"), (0, "240"))

    body = await _get(client, token, portfolio_id, benchmark=benchmark_pln.key)

    bench = body["benchmark"]
    assert bench["unavailable_reason"] is None
    assert [Decimal(p["index"]) for p in bench["points"]] == [Decimal("100"), Decimal("120")]
    assert [Decimal(p["index"]) for p in body["points"]] == [Decimal("100"), Decimal("110")]


async def test_benchmark_carries_the_proxy_label(
    client: AsyncClient, db_session: AsyncSession, benchmark_pln: BenchmarkFixture
) -> None:
    """`key` to o co pytał użytkownik, `symbol` to czym policzono — odpowiedź
    niesie oba, więc podmiana jest jawna."""
    token = await _register_and_login(client, EMAIL_A)
    portfolio_id = await _create_portfolio(client, token)
    await _add_valuations(db_session, portfolio_id, (1, "1000"), (0, "1100"))
    await _add_quotes(db_session, benchmark_pln.asset, (1, "200"), (0, "240"))

    bench = (await _get(client, token, portfolio_id, benchmark="WIG20"))["benchmark"]

    assert bench["key"] == "WIG20"
    assert bench["symbol"] == benchmark_pln.asset.symbol
    assert bench["approximate"] is True
    assert bench["note"]


async def test_foreign_benchmark_is_converted_to_pln(
    client: AsyncClient, db_session: AsyncSession, benchmark_foreign: BenchmarkFixture
) -> None:
    """Decyzja 4 planu: benchmark w walucie obcej idzie przez kurs NBP, bo
    kurs jest częścią realnego wyniku inwestora. Indeks bez zmiany, złoty
    słabszy o 10% → benchmark w PLN na +10%."""
    token = await _register_and_login(client, EMAIL_A)
    portfolio_id = await _create_portfolio(client, token)
    await _add_valuations(db_session, portfolio_id, (1, "1000"), (0, "1100"))
    await _add_quotes(db_session, benchmark_foreign.asset, (1, "5000"), (0, "5000"))
    await _add_fx(db_session, (1, "4"), (0, "4.4"))

    bench = (await _get(client, token, portfolio_id, benchmark="^GSPC"))["benchmark"]

    assert bench["currency"] == "XTS"
    assert [Decimal(p["index"]) for p in bench["points"]] == [Decimal("100"), Decimal("110")]


async def test_missing_fx_is_reported_not_silently_skipped(
    client: AsyncClient, db_session: AsyncSession, benchmark_foreign: BenchmarkFixture
) -> None:
    """Notowanie jest, kursu nie ma — cichy mnożnik 1 udawałby, że wartość
    w walucie obcej jest kwotą w PLN."""
    token = await _register_and_login(client, EMAIL_A)
    portfolio_id = await _create_portfolio(client, token)
    await _add_valuations(db_session, portfolio_id, (1, "1000"), (0, "1100"))
    await _add_quotes(db_session, benchmark_foreign.asset, (1, "5000"), (0, "5000"))

    bench = (await _get(client, token, portfolio_id, benchmark="^GSPC"))["benchmark"]

    assert bench["points"] == []
    assert bench["unavailable_reason"]


async def test_benchmark_without_quotes_says_why(
    client: AsyncClient, db_session: AsyncSession, benchmark_pln: BenchmarkFixture
) -> None:
    """Brak wspólnego punktu odniesienia → brak linii ORAZ powód. Pusta seria
    bez wyjaśnienia wygląda jak awaria."""
    token = await _register_and_login(client, EMAIL_A)
    portfolio_id = await _create_portfolio(client, token)
    await _add_valuations(db_session, portfolio_id, (1, "1000"), (0, "1100"))

    bench = (await _get(client, token, portfolio_id, benchmark="WIG20"))["benchmark"]

    assert bench["points"] == []
    assert bench["unavailable_reason"]


async def test_quote_from_before_the_window_anchors_the_series(
    client: AsyncClient, db_session: AsyncSession, benchmark_pln: BenchmarkFixture
) -> None:
    """Regresja na `list_prices_with_carry`: okno portfela zaczyna się w dniu
    bez sesji. Bez dociągnięcia notowania sprzed okna benchmark gubiłby
    początek serii dokładnie wtedy, gdy zakres wypada w weekend."""
    token = await _register_and_login(client, EMAIL_A)
    portfolio_id = await _create_portfolio(client, token)
    await _add_valuations(db_session, portfolio_id, (1, "1000"), (0, "1100"))
    await _add_quotes(db_session, benchmark_pln.asset, (9, "200"), (0, "240"))

    bench = (await _get(client, token, portfolio_id, benchmark="WIG20"))["benchmark"]

    assert len(bench["points"]) == 2
    assert Decimal(bench["points"][0]["index"]) == Decimal("100")
    assert bench["points"][0]["as_of"] != bench["points"][0]["date"], (
        "`as_of` musi pokazać, że wartość pochodzi z wcześniejszej sesji"
    )


async def test_no_benchmark_param_gives_null(client: AsyncClient, db_session: AsyncSession) -> None:
    token = await _register_and_login(client, EMAIL_A)
    portfolio_id = await _create_portfolio(client, token)
    await _add_valuations(db_session, portfolio_id, (1, "1000"), (0, "1100"))

    assert (await _get(client, token, portfolio_id))["benchmark"] is None


async def test_unknown_benchmark_is_422(client: AsyncClient) -> None:
    """Zamknięty enum: `?benchmark=CDR` to nie „aktywo bez historii", tylko
    wartość spoza kontraktu."""
    token = await _register_and_login(client, EMAIL_A)
    portfolio_id = await _create_portfolio(client, token)

    resp = await client.get(
        f"/api/portfolios/{portfolio_id}/performance",
        params={"benchmark": "CDR"},
        headers=_auth(token),
    )

    assert resp.status_code == 422


async def test_benchmark_is_a_separate_cache_key(
    client: AsyncClient, db_session: AsyncSession, benchmark_pln: BenchmarkFixture
) -> None:
    """Bez benchmarku i z benchmarkiem to dwie różne odpowiedzi — wspólny
    klucz podałby jedną z nich zamiast drugiej."""
    token = await _register_and_login(client, EMAIL_A)
    portfolio_id = await _create_portfolio(client, token)
    await _add_valuations(db_session, portfolio_id, (1, "1000"), (0, "1100"))
    await _add_quotes(db_session, benchmark_pln.asset, (1, "200"), (0, "240"))

    plain = await _get(client, token, portfolio_id)
    with_bench = await _get(client, token, portfolio_id, benchmark="WIG20")

    assert plain["benchmark"] is None
    assert with_bench["benchmark"] is not None


async def test_new_benchmark_quote_invalidates_the_cache(
    client: AsyncClient, db_session: AsyncSession, benchmark_pln: BenchmarkFixture
) -> None:
    """Notowania benchmarku przychodzą z ingestii rynkowej, nie ze snapshotów
    portfela — `valuations_marker` na nie nie reaguje. Bez własnego segmentu
    świeżości wykres stałby do wygaśnięcia TTL."""
    token = await _register_and_login(client, EMAIL_A)
    portfolio_id = await _create_portfolio(client, token)
    await _add_valuations(db_session, portfolio_id, (2, "1000"), (1, "1100"), (0, "1200"))
    await _add_quotes(db_session, benchmark_pln.asset, (2, "200"), (1, "220"))

    before = (await _get(client, token, portfolio_id, benchmark="WIG20"))["benchmark"]
    assert len(before["points"]) == 3, "ostatni dzień niesie notowanie z dnia poprzedniego"
    assert Decimal(before["points"][-1]["index"]) == Decimal("110")

    await _add_quotes(db_session, benchmark_pln.asset, (0, "260"))
    after = (await _get(client, token, portfolio_id, benchmark="WIG20"))["benchmark"]

    assert Decimal(after["points"][-1]["index"]) == Decimal("130")
