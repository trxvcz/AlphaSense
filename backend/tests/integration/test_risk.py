"""Testy `GET /portfolios/{id}/risk` (plan krok 41b, etap 8).

Matematyka ma pełne pokrycie w `tests/unit/test_risk.py` (bez bazy, na
znanych liczbach). Tutaj wyłącznie orkiestracja: autoryzacja zasobowa,
serializacja `Decimal`→string, próg `MIN_OBSERVATIONS`, i rzecz, której
czysta matematyka złapać nie może — **że Sharpe bierze stopę z bazy, a przy
jej braku zwraca `null` z powodem, zamiast liczby policzonej z zera**.

Endpoint czyta `portfolio_valuations` i `nbp_reference_rates`. Snapshoty
sprzątają się same (`ON DELETE CASCADE` z `portfolios`, które kasuje
`_clean_auth_tables`), stopy referencyjne **nie** — nie wiszą na żadnym
użytkowniku — więc fixture czyści je jawnie przed i po.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.analytics import service as analytics_service
from app.modules.analytics.risk import MIN_OBSERVATIONS
from app.modules.marketdata.models import Asset, NbpReferenceRate, Price
from app.modules.portfolio.models import PortfolioValuation
from app.modules.portfolio.service import today

EMAIL_A = "risk-a@example.com"
EMAIL_B = "risk-b@example.com"
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
        "/api/portfolios", json={"name": "Ryzyko", "type": "standard"}, headers=_auth(token)
    )
    assert resp.status_code == 201, resp.text
    portfolio_id: str = resp.json()["id"]
    return portfolio_id


async def _add_valuations(db_session: AsyncSession, portfolio_id: str, values: list[str]) -> None:
    """`values[i]` to wycena sprzed `len(values) - 1 - i` dni (rosnąco po dacie).

    Liczone względem `today()`, nie na stałych datach — `range` odcina okno
    od dnia dzisiejszego, więc test na sztywnej dacie przestałby cokolwiek
    sprawdzać wraz z upływem czasu.
    """
    d = today()
    last = len(values) - 1
    db_session.add_all(
        [
            PortfolioValuation(
                portfolio_id=uuid.UUID(portfolio_id),
                date=d - timedelta(days=last - offset),
                value_pln=Decimal(value),
                composition_change=False,
            )
            for offset, value in enumerate(values)
        ]
    )
    await db_session.commit()


def _wobbling(n: int) -> list[str]:
    """Seria falująca wokół 1000 — dość zmienna, żeby metryki miały sens,
    i deterministyczna, żeby test nie zależał od losowości."""
    return [str(1000 + (offset % 5) * 10 - (offset % 3) * 7) for offset in range(n)]


@pytest_asyncio.fixture
async def clean_rates(db_session: AsyncSession) -> AsyncGenerator[AsyncSession, None]:
    await db_session.execute(delete(NbpReferenceRate))
    await db_session.commit()
    yield db_session
    await db_session.execute(delete(NbpReferenceRate))
    await db_session.commit()


async def _seed_rate(db_session: AsyncSession, *, years_back: int = 30) -> None:
    """Jedna stopa obowiązująca od dawna — pokrywa cały okres testowy."""
    db_session.add(
        NbpReferenceRate(
            effective_from=today() - timedelta(days=365 * years_back),
            rate=Decimal("0.0375"),
            source="nbp",
            fetched_at=datetime.now(UTC),
        )
    )
    await db_session.commit()


async def _get(client: AsyncClient, token: str, portfolio_id: str, **params: str) -> dict:
    resp = await client.get(
        f"/api/portfolios/{portfolio_id}/risk", params=params, headers=_auth(token)
    )
    assert resp.status_code == 200, resp.text
    body: dict = resp.json()
    return body


# --- ścieżka szczęśliwa ----------------------------------------------------


async def test_returns_all_metrics_for_long_enough_series(
    client: AsyncClient, clean_rates: AsyncSession
) -> None:
    token = await _register_and_login(client, EMAIL_A)
    portfolio_id = await _create_portfolio(client, token)
    await _add_valuations(clean_rates, portfolio_id, _wobbling(60))
    await _seed_rate(clean_rates)

    body = await _get(client, token, portfolio_id)

    assert body["observations"] == 59
    assert body["min_observations"] == MIN_OBSERVATIONS
    assert body["volatility"] is not None
    assert body["volatility_unavailable_reason"] is None
    assert body["sharpe"] is not None
    assert body["sharpe_unavailable_reason"] is None
    assert body["risk_free_label"] is not None
    assert body["max_drawdown"] is not None
    assert len(body["underwater"]) == 60
    assert body["monthly_returns"]
    # Bez `?benchmark=` beta nie jest liczona — i to nie jest brak danych.
    assert body["beta"] is None


async def test_amounts_are_serialized_as_strings(
    client: AsyncClient, clean_rates: AsyncSession
) -> None:
    """CLAUDE.md #3.1 — ułamki jako string, nigdy `float` w JSON."""
    token = await _register_and_login(client, EMAIL_A)
    portfolio_id = await _create_portfolio(client, token)
    await _add_valuations(clean_rates, portfolio_id, _wobbling(60))
    await _seed_rate(clean_rates)

    body = await _get(client, token, portfolio_id)

    assert isinstance(body["volatility"], str)
    assert isinstance(body["sharpe"], str)
    assert isinstance(body["max_drawdown"]["value"], str)
    assert isinstance(body["underwater"][0]["value"], str)
    assert isinstance(body["monthly_returns"][0]["ret"], str)


async def test_drawdown_is_negative_and_dated(
    client: AsyncClient, clean_rates: AsyncSession
) -> None:
    """1000 → 1200 → 900 → 1000: obsunięcie -25%, nieodrobione."""
    token = await _register_and_login(client, EMAIL_A)
    portfolio_id = await _create_portfolio(client, token)
    await _add_valuations(clean_rates, portfolio_id, ["1000", "1200", "900", "1000"])

    body = await _get(client, token, portfolio_id)

    drawdown = body["max_drawdown"]
    assert Decimal(drawdown["value"]) == Decimal("-0.25")
    assert drawdown["peak_date"] == (today() - timedelta(days=2)).isoformat()
    assert drawdown["trough_date"] == (today() - timedelta(days=1)).isoformat()
    assert drawdown["recovered_at"] is None


# --- brak danych: `null` z powodem, nigdy liczba ---------------------------


async def test_short_series_has_no_metrics_but_explains_why(
    client: AsyncClient, clean_rates: AsyncSession
) -> None:
    token = await _register_and_login(client, EMAIL_A)
    portfolio_id = await _create_portfolio(client, token)
    await _add_valuations(clean_rates, portfolio_id, _wobbling(5))
    await _seed_rate(clean_rates)

    body = await _get(client, token, portfolio_id)

    assert body["volatility"] is None
    assert body["volatility_unavailable_reason"]
    assert body["sharpe"] is None
    assert body["sharpe_unavailable_reason"]
    # Drawdown NIE wymaga progu — jedno obsunięcie jest faktem niezależnie
    # od długości serii, w odróżnieniu od oszacowania rozkładu.
    assert body["max_drawdown"] is not None


async def test_sharpe_is_null_without_reference_rate_but_volatility_is_not(
    client: AsyncClient, clean_rates: AsyncSession
) -> None:
    """Sedno kroku 41a+b: brak stopy zabiera Sharpe'a, nie całą stronę.

    Gdyby przy pustej tabeli stóp podstawić zero, Sharpe policzyłby się bez
    śladu i wyglądał identycznie jak ten z prawdziwej stopy.
    """
    token = await _register_and_login(client, EMAIL_A)
    portfolio_id = await _create_portfolio(client, token)
    await _add_valuations(clean_rates, portfolio_id, _wobbling(60))
    # Świadomie BEZ `_seed_rate` — tabela `nbp_reference_rates` jest pusta.

    body = await _get(client, token, portfolio_id)

    assert body["volatility"] is not None
    assert body["sharpe"] is None
    assert "stop" in body["sharpe_unavailable_reason"].lower()
    assert body["risk_free_label"] is None


async def test_rate_starting_after_the_series_does_not_leak_backwards(
    client: AsyncClient, clean_rates: AsyncSession
) -> None:
    """Stopa ogłoszona PO okresie nie może być użyta do liczenia go wstecz."""
    token = await _register_and_login(client, EMAIL_A)
    portfolio_id = await _create_portfolio(client, token)
    await _add_valuations(clean_rates, portfolio_id, _wobbling(60))
    clean_rates.add(
        NbpReferenceRate(
            effective_from=today() + timedelta(days=1),
            rate=Decimal("0.0375"),
            source="nbp",
            fetched_at=datetime.now(UTC),
        )
    )
    await clean_rates.commit()

    body = await _get(client, token, portfolio_id)

    assert body["sharpe"] is None
    assert body["volatility"] is not None


async def test_portfolio_without_history_has_no_metrics(
    client: AsyncClient, clean_rates: AsyncSession
) -> None:
    """Portfel bez snapshotów: same `null`, zero pustych wykresów."""
    token = await _register_and_login(client, EMAIL_A)
    portfolio_id = await _create_portfolio(client, token)

    body = await _get(client, token, portfolio_id)

    assert body["observations"] == 0
    assert body["first_date"] is None
    assert body["volatility"] is None
    assert body["max_drawdown"] is None
    assert body["underwater"] == []
    assert body["monthly_returns"] == []


# --- beta ------------------------------------------------------------------
#
# Ten sam wzorzec co w `test_performance.py`: beta liczona na WŁASNYM aktywie
# o losowym symbolu, z podmienionym `service.BENCHMARKS`, a nie na realnym
# `^GSPC`. Powód jest tam opisany szerzej i tu identyczny — realne benchmarki
# mają w bazie dev pełną historię z `make backfill`, więc test „benchmark bez
# notowań" nigdy nie zobaczyłby pustki, a test na znanych liczbach zderzałby
# się z prawdziwymi notowaniami.


@dataclass
class BenchmarkFixture:
    asset: Asset
    key: str


@pytest_asyncio.fixture
async def benchmark(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> AsyncGenerator[BenchmarkFixture, None]:
    asset = Asset(
        symbol=f"BMK{uuid.uuid4().hex[:8]}",
        name="Benchmark testowy",
        asset_class="index",
        market_code="GPW",
        currency="PLN",
    )
    db_session.add(asset)
    await db_session.commit()
    await db_session.refresh(asset)

    real = analytics_service.BENCHMARKS["WIG20"]
    monkeypatch.setitem(
        analytics_service.BENCHMARKS,
        "WIG20",
        analytics_service.BenchmarkSpec(
            key=real.key,
            symbol=asset.symbol,
            label=real.label,
            approximate=real.approximate,
            note=real.note,
        ),
    )

    yield BenchmarkFixture(asset=asset, key="WIG20")

    await db_session.execute(delete(Price).where(Price.asset_id == asset.id))
    await db_session.execute(delete(Asset).where(Asset.id == asset.id))
    await db_session.commit()


async def _add_quotes(db_session: AsyncSession, asset: Asset, values: list[str]) -> None:
    """Notowania benchmarku na tych samych datach co snapshoty portfela."""
    d = today()
    last = len(values) - 1
    db_session.add_all(
        [
            Price(
                asset_id=asset.id,
                date=d - timedelta(days=last - offset),
                close=Decimal(value),
                close_adj=Decimal(value),
                source="test",
            )
            for offset, value in enumerate(values)
        ]
    )
    await db_session.commit()


async def test_beta_of_portfolio_tracking_the_benchmark_is_one(
    client: AsyncClient, clean_rates: AsyncSession, benchmark: BenchmarkFixture
) -> None:
    """Przypadek referencyjny: portfel poruszający się dokładnie jak
    benchmark ma betę 1. Policzalny w głowie, więc nadaje się na test
    end-to-end całej ścieżki (snapshoty → ogniwa → parowanie po datach)."""
    token = await _register_and_login(client, EMAIL_A)
    portfolio_id = await _create_portfolio(client, token)
    values = _wobbling(60)
    await _add_valuations(clean_rates, portfolio_id, values)
    await _add_quotes(clean_rates, benchmark.asset, values)

    body = await _get(client, token, portfolio_id, benchmark=benchmark.key)

    assert body["beta"]["value"] is not None
    assert Decimal(body["beta"]["value"]) == Decimal("1")
    assert body["beta"]["observations"] == 59
    assert body["beta"]["unavailable_reason"] is None
    assert body["beta"]["label"]


async def test_beta_of_double_amplitude_portfolio_is_two(
    client: AsyncClient, clean_rates: AsyncSession, benchmark: BenchmarkFixture
) -> None:
    """Benchmark ±1%, portfel ±2% w te same dni → beta 2."""
    token = await _register_and_login(client, EMAIL_A)
    portfolio_id = await _create_portfolio(client, token)
    bench_values = [
        str(Decimal("1000") * (Decimal("1.01") if i % 2 else Decimal("0.99"))) for i in range(60)
    ]
    port_values = [
        str(Decimal("1000") * (Decimal("1.02") if i % 2 else Decimal("0.98"))) for i in range(60)
    ]
    await _add_valuations(clean_rates, portfolio_id, port_values)
    await _add_quotes(clean_rates, benchmark.asset, bench_values)

    body = await _get(client, token, portfolio_id, benchmark=benchmark.key)

    assert Decimal(body["beta"]["value"]).quantize(Decimal("0.01")) == Decimal("2.00")


async def test_beta_reports_reason_when_benchmark_has_no_history(
    client: AsyncClient, clean_rates: AsyncSession, benchmark: BenchmarkFixture
) -> None:
    """Brak notowań benchmarku daje powód po polsku, nie cichego `null`.

    Wykres bez linii i wskaźnik bez liczby, oba bez wyjaśnienia, wyglądają
    w UI jak awaria (CLAUDE.md #3.15).
    """
    token = await _register_and_login(client, EMAIL_A)
    portfolio_id = await _create_portfolio(client, token)
    await _add_valuations(clean_rates, portfolio_id, _wobbling(60))
    # Świadomie BEZ `_add_quotes` — benchmark istnieje, ale nie ma notowań.

    body = await _get(client, token, portfolio_id, benchmark=benchmark.key)

    assert body["beta"] is not None
    assert body["beta"]["value"] is None
    assert body["beta"]["unavailable_reason"]


# --- izolacja danych -------------------------------------------------------


async def test_foreign_portfolio_is_404_not_403(
    client: AsyncClient, clean_rates: AsyncSession
) -> None:
    """Cudzy portfel to 404 — nie zdradzamy istnienia zasobu (skill
    `izolacja-danych`). Trasa jest też objęta parametryzowanym
    `tests/test_isolation.py` przez parametr `portfolio_id`; ten test
    zostaje jako jawny, czytelny przypadek przy samym endpoincie."""
    token_a = await _register_and_login(client, EMAIL_A)
    portfolio_a = await _create_portfolio(client, token_a)
    await _add_valuations(clean_rates, portfolio_a, _wobbling(60))
    token_b = await _register_and_login(client, EMAIL_B)

    resp = await client.get(f"/api/portfolios/{portfolio_a}/risk", headers=_auth(token_b))

    assert resp.status_code == 404, resp.text


async def test_requires_authentication(client: AsyncClient) -> None:
    token = await _register_and_login(client, EMAIL_A)
    portfolio_id = await _create_portfolio(client, token)

    resp = await client.get(f"/api/portfolios/{portfolio_id}/risk")

    assert resp.status_code == 401, resp.text


async def test_unknown_benchmark_is_422(client: AsyncClient) -> None:
    """Zamknięty enum — dowolny symbol nie przechodzi do serwisu."""
    token = await _register_and_login(client, EMAIL_A)
    portfolio_id = await _create_portfolio(client, token)

    resp = await client.get(
        f"/api/portfolios/{portfolio_id}/risk",
        params={"benchmark": "NIEISTNIEJACY"},
        headers=_auth(token),
    )

    assert resp.status_code == 422, resp.text


@pytest.mark.parametrize("range_", ["1M", "1Y", "max"])
async def test_range_parameter_is_accepted(
    client: AsyncClient, clean_rates: AsyncSession, range_: str
) -> None:
    token = await _register_and_login(client, EMAIL_A)
    portfolio_id = await _create_portfolio(client, token)
    await _add_valuations(clean_rates, portfolio_id, _wobbling(60))

    body = await _get(client, token, portfolio_id, range=range_)

    assert body["range"] == range_
