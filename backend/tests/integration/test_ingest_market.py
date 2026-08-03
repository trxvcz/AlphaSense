"""Testy `worker.jobs.ingest_market` (plan krok 23, etap 4).

Testy integracyjne (prawdziwa baza, jak `db_session` w `conftest.py`), zero
sieci — `build_fallback_chain`/`list_active_assets`/`list_fx_currencies` są
podmieniane (`monkeypatch.setattr` na atrybucie modułu `ingest_market`, nie
na `service.py`/`repository.py` — to konkretne nazwy zaimportowane *do*
`worker/jobs/ingest_market.py`, patrz `unittest.mock`/`pytest-mock`
dokumentacja „where to patch") na sztuczne dostawce zwracające znane dane,
tak jak `tests/unit/test_fallback_chain.py` robi to dla `FallbackChain`
samego. Świadomie **nie** monkeypatchujemy globalnych `assets`/`fx_rates`
seedowanych przez `make seed` (np. realnych kursów USD/EUR) — `list_active_
assets`/`list_fx_currencies` są zastępowane sztucznymi wersjami zwracającymi
wyłącznie dane tymczasowe utworzone w danym teście, żeby żaden test nie
nadpisał prawdziwych `fx_rates`/`prices` sfałszowanymi wartościami we
współdzielonej bazie dev.

Zakłada istnienie rynków `GPW`/`FX` w słowniku `markets` (seed, `make seed`)
— ta sama konwencja co `tests/integration/test_marketdata_repository.py`
(`temp_asset` na `market_code="COMMODITY"`).
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncGenerator, Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

import worker.jobs.ingest_market as ingest_market_module
from app.modules.marketdata.models import Asset, AssetSourceMap, FxRate, IngestionRun, Price
from app.modules.marketdata.providers.base import Capability, FxQuote, PriceBar
from worker.jobs.ingest_market import ingest_market

_RUN_DATE = date(2026, 7, 20)


@dataclass
class _FakeProvider:
    """Duck-typed odpowiednik `Guarded` — `ingest_market.py` woła tylko
    `.name`/`.supports`/`.get_ohlcv`/`.get_fx`, nic więcej (żadnego
    limitera/breakera potrzebnego w testach tej warstwy, to już pokrywa
    `tests/unit/test_fallback_chain.py`/`test_rate_limiter.py`).
    """

    name: str
    supports: set[Capability]
    ohlcv_by_symbol: dict[str, list[PriceBar] | Exception] = field(default_factory=dict)
    fx_by_currency: dict[str, list[FxQuote] | Exception] = field(default_factory=dict)

    async def get_ohlcv(self, symbol: str, start: date, end: date) -> list[PriceBar]:
        result = self.ohlcv_by_symbol[symbol]
        if isinstance(result, Exception):
            raise result
        return result

    async def get_fx(self, currency: str, start: date, end: date) -> list[FxQuote]:
        result = self.fx_by_currency[currency]
        if isinstance(result, Exception):
            raise result
        return result

    async def get_metadata(self, symbol: str) -> None:
        return None


def _returning(value: Any) -> Callable[..., Awaitable[Any]]:
    async def _fn(*_args: Any, **_kwargs: Any) -> Any:
        return value

    return _fn


async def _latest_ingestion_run(
    db: AsyncSession, market_code: str, *, after: datetime
) -> IngestionRun:
    result = await db.execute(
        select(IngestionRun)
        .where(IngestionRun.market_code == market_code, IngestionRun.started_at >= after)
        .order_by(IngestionRun.started_at.desc())
        .limit(1)
    )
    run = result.scalar_one_or_none()
    assert run is not None, f"brak IngestionRun dla {market_code!r} po {after}"
    return run


@pytest_asyncio.fixture
async def temp_asset(db_session: AsyncSession) -> AsyncGenerator[Asset, None]:
    """Aktywo tymczasowe na (już istniejącym z seeda) rynku `GPW`."""
    asset = Asset(
        symbol=f"TEST-{uuid.uuid4().hex[:8]}",
        name="Test Asset (tymczasowy, test ingest_market)",
        asset_class="equity",
        market_code="GPW",
        currency="PLN",
    )
    db_session.add(asset)
    await db_session.commit()
    await db_session.refresh(asset)
    yield asset
    await db_session.execute(delete(Price).where(Price.asset_id == asset.id))
    await db_session.execute(delete(AssetSourceMap).where(AssetSourceMap.asset_id == asset.id))
    await db_session.execute(delete(Asset).where(Asset.id == asset.id))
    await db_session.commit()


@pytest_asyncio.fixture(autouse=True)
async def _cleanup_ingestion_runs(db_session: AsyncSession) -> AsyncGenerator[None, None]:
    """Usuwa `ingestion_runs` utworzone w trakcie testu (rynki `GPW`/`FX`,
    jedyne użyte w tym pliku) — logi ingestii to nie coś, co inne testy
    (np. `/meta/freshness`, `test_meta_freshness.py`) powinny zobaczyć jako
    prawdziwy przebieg.
    """
    before = datetime.now(UTC)
    yield
    await db_session.execute(
        delete(IngestionRun).where(
            IngestionRun.market_code.in_(["GPW", "FX"]), IngestionRun.started_at >= before
        )
    )
    await db_session.commit()


@pytest.fixture
def sentry_messages(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str]]:
    """Przechwytuje alerty `sentry_sdk.capture_message` z joba (krok 37).

    Podmiana na module `sentry_sdk`, bo `ingest_market.py` importuje cały
    moduł, nie samą funkcję. Bez `SENTRY_DSN` prawdziwe `capture_message`
    jest no-opem, więc test bez tego podwójnego nie odróżniłby „alert
    wysłany" od „alertu nie ma wcale".
    """
    captured: list[tuple[str, str]] = []

    def _spy(message: str, level: str = "info", **_kwargs: Any) -> None:
        captured.append((message, level))

    monkeypatch.setattr(ingest_market_module.sentry_sdk, "capture_message", _spy)
    return captured


async def test_ingest_market_ohlcv_success_writes_prices_and_ingestion_run(
    db_session: AsyncSession, temp_asset: Asset, monkeypatch: pytest.MonkeyPatch
) -> None:
    bar = PriceBar(
        date=_RUN_DATE,
        open=Decimal("100"),
        high=Decimal("101"),
        low=Decimal("99"),
        close=Decimal("100.5"),
        close_adj=Decimal("100.5"),
        volume=1000,
    )
    fake = _FakeProvider("fake", {Capability.OHLCV}, ohlcv_by_symbol={"FAKESYM": [bar]})
    monkeypatch.setattr(ingest_market_module, "build_fallback_chain", lambda market_code: [fake])
    monkeypatch.setattr(ingest_market_module, "list_active_assets", _returning([temp_asset]))

    db_session.add(
        AssetSourceMap(
            asset_id=temp_asset.id, provider="fake", provider_symbol="FAKESYM", priority=1
        )
    )
    await db_session.commit()

    before = datetime.now(UTC)
    await ingest_market("GPW", run_date=_RUN_DATE)

    result = await db_session.execute(select(Price).where(Price.asset_id == temp_asset.id))
    rows = result.scalars().all()
    assert len(rows) == 1
    assert rows[0].close_adj == Decimal("100.5")

    run = await _latest_ingestion_run(db_session, "GPW", after=before)
    assert run.status == "ok"
    assert run.assets_total == 1
    assert run.assets_ok == 1
    assert run.provider == "fake"
    assert run.error is None
    assert run.finished_at is not None


async def test_ingest_market_second_run_same_day_overwrites_not_duplicates(
    db_session: AsyncSession, temp_asset: Asset, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ingest_market_module, "list_active_assets", _returning([temp_asset]))

    db_session.add(
        AssetSourceMap(
            asset_id=temp_asset.id, provider="fake", provider_symbol="FAKESYM", priority=1
        )
    )
    await db_session.commit()

    first_bar = PriceBar(
        date=_RUN_DATE,
        open=Decimal("100"),
        high=Decimal("101"),
        low=Decimal("99"),
        close=Decimal("100.5"),
        close_adj=Decimal("100.5"),
        volume=1000,
    )
    monkeypatch.setattr(
        ingest_market_module,
        "build_fallback_chain",
        lambda market_code: [
            _FakeProvider("fake", {Capability.OHLCV}, ohlcv_by_symbol={"FAKESYM": [first_bar]})
        ],
    )
    await ingest_market("GPW", run_date=_RUN_DATE)

    # Drugi przebieg tego samego dnia — dostawca tym razem zwraca inne
    # wartości; idempotencja `upsert_prices` (ON CONFLICT DO UPDATE) musi
    # nadpisać wiersz, nie dodać drugiego (CLAUDE.md #3.9).
    second_bar = PriceBar(
        date=_RUN_DATE,
        open=Decimal("100"),
        high=Decimal("103"),
        low=Decimal("99"),
        close=Decimal("102"),
        close_adj=Decimal("102"),
        volume=2000,
    )
    monkeypatch.setattr(
        ingest_market_module,
        "build_fallback_chain",
        lambda market_code: [
            _FakeProvider("fake", {Capability.OHLCV}, ohlcv_by_symbol={"FAKESYM": [second_bar]})
        ],
    )
    await ingest_market("GPW", run_date=_RUN_DATE)

    result = await db_session.execute(select(Price).where(Price.asset_id == temp_asset.id))
    rows = result.scalars().all()
    assert len(rows) == 1  # nadpisany, nie zduplikowany
    assert rows[0].close_adj == Decimal("102")
    assert rows[0].volume == 2000

    # `ingestion_runs` to log append-only per przebieg (nie ceny/kursy) —
    # dwa uruchomienia tego samego dnia to świadomie dwa wiersze logu.
    runs = await db_session.execute(select(IngestionRun).where(IngestionRun.market_code == "GPW"))
    assert len(runs.scalars().all()) >= 2


async def test_ingest_market_continues_after_one_asset_fails(
    db_session: AsyncSession,
    temp_asset: Asset,
    monkeypatch: pytest.MonkeyPatch,
    sentry_messages: list[tuple[str, str]],
) -> None:
    other_asset = Asset(
        symbol=f"TEST-{uuid.uuid4().hex[:8]}",
        name="Test Asset 2 (tymczasowy, test ingest_market)",
        asset_class="equity",
        market_code="GPW",
        currency="PLN",
    )
    db_session.add(other_asset)
    await db_session.commit()
    await db_session.refresh(other_asset)

    bar = PriceBar(
        date=_RUN_DATE,
        open=Decimal("50"),
        high=Decimal("51"),
        low=Decimal("49"),
        close=Decimal("50.5"),
        close_adj=Decimal("50.5"),
        volume=500,
    )
    fake = _FakeProvider(
        "fake",
        {Capability.OHLCV},
        ohlcv_by_symbol={
            "FAILS": RuntimeError("dostawca padł dla tego symbolu"),
            "WORKS": [bar],
        },
    )
    monkeypatch.setattr(ingest_market_module, "build_fallback_chain", lambda market_code: [fake])
    # kolejność ważna tylko dla czytelności asercji błędu niżej
    monkeypatch.setattr(
        ingest_market_module, "list_active_assets", _returning([temp_asset, other_asset])
    )

    db_session.add_all(
        [
            AssetSourceMap(
                asset_id=temp_asset.id, provider="fake", provider_symbol="FAILS", priority=1
            ),
            AssetSourceMap(
                asset_id=other_asset.id, provider="fake", provider_symbol="WORKS", priority=1
            ),
        ]
    )
    await db_session.commit()

    try:
        before = datetime.now(UTC)
        await ingest_market("GPW", run_date=_RUN_DATE)

        # aktywo, które zawiodło, nie ma cen
        no_prices = await db_session.execute(select(Price).where(Price.asset_id == temp_asset.id))
        assert no_prices.scalars().all() == []

        # drugie aktywo mimo to zostało zapisane — job nie przerwał się na
        # pierwszym błędzie (SKILL `job-eod`, reguła 6)
        ok_prices = await db_session.execute(select(Price).where(Price.asset_id == other_asset.id))
        rows = ok_prices.scalars().all()
        assert len(rows) == 1
        assert rows[0].close_adj == Decimal("50.5")

        run = await _latest_ingestion_run(db_session, "GPW", after=before)
        assert run.status == "partial"
        assert run.assets_total == 2
        assert run.assets_ok == 1
        assert run.error is not None
        assert temp_asset.symbol in run.error

        # Krok 37: przebieg częściowy to `warning`, nie `error` — część
        # aktywów ma świeże dane, więc widok użytkownika nadal się liczy.
        assert [level for _, level in sentry_messages] == ["warning"]
        assert "GPW" in sentry_messages[0][0]
    finally:
        await db_session.execute(delete(Price).where(Price.asset_id == other_asset.id))
        await db_session.execute(
            delete(AssetSourceMap).where(AssetSourceMap.asset_id == other_asset.id)
        )
        await db_session.execute(delete(Asset).where(Asset.id == other_asset.id))
        await db_session.commit()


async def test_ingest_market_total_failure_alerts_sentry_with_error_level(
    db_session: AsyncSession,
    temp_asset: Asset,
    monkeypatch: pytest.MonkeyPatch,
    sentry_messages: list[tuple[str, str]],
) -> None:
    """Przebieg bez ani jednego zaciągniętego aktywa (`status=failed`) wysyła
    alert o poziomie `error` (krok 37, SKILL `job-eod` reguła 6).

    Sam `structlog.error` nie wystarcza: `structlog` w tym repo pisze poza
    `logging`, więc bez jawnego `capture_message` cicha awaria rynku nie
    zostawiłaby żadnego śladu poza logiem kontenera — a wycena portfeli
    policzyłaby się na wczorajszych cenach, nie sygnalizując tego w UI.
    """
    fake = _FakeProvider(
        "fake",
        {Capability.OHLCV},
        ohlcv_by_symbol={"FAILS": RuntimeError("dostawca padł dla tego symbolu")},
    )
    monkeypatch.setattr(ingest_market_module, "build_fallback_chain", lambda market_code: [fake])
    monkeypatch.setattr(ingest_market_module, "list_active_assets", _returning([temp_asset]))

    db_session.add(
        AssetSourceMap(asset_id=temp_asset.id, provider="fake", provider_symbol="FAILS", priority=1)
    )
    await db_session.commit()

    before = datetime.now(UTC)
    status = await ingest_market("GPW", run_date=_RUN_DATE)

    assert status == "failed"
    run = await _latest_ingestion_run(db_session, "GPW", after=before)
    assert run.status == "failed"

    assert [level for _, level in sentry_messages] == ["error"]
    assert "GPW" in sentry_messages[0][0]


async def test_ingest_market_fx_writes_fx_rates(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    quote = FxQuote(currency="ZZZ", date=_RUN_DATE, rate_pln=Decimal("4.2000"))
    fake = _FakeProvider("nbp", {Capability.FX}, fx_by_currency={"ZZZ": [quote]})
    monkeypatch.setattr(ingest_market_module, "build_fallback_chain", lambda market_code: [fake])
    # Nie dotykamy prawdziwych walut zasianych przez `make seed`
    # (USD/EUR/...) — tylko naszej testowej `ZZZ` (patrz docstring modułu).
    monkeypatch.setattr(ingest_market_module, "list_fx_currencies", _returning(["ZZZ"]))

    try:
        before = datetime.now(UTC)
        await ingest_market("FX", run_date=_RUN_DATE)

        result = await db_session.execute(
            select(FxRate).where(FxRate.currency == "ZZZ", FxRate.date == _RUN_DATE)
        )
        row = result.scalar_one()
        assert row.rate_pln == Decimal("4.2000")

        run = await _latest_ingestion_run(db_session, "FX", after=before)
        assert run.status == "ok"
        assert run.assets_total == 1
        assert run.assets_ok == 1
        assert run.provider == "nbp"
    finally:
        await db_session.execute(delete(FxRate).where(FxRate.currency == "ZZZ"))
        await db_session.commit()


async def test_ingest_market_unknown_market_code_is_noop(
    db_session: AsyncSession,
) -> None:
    before = datetime.now(UTC)
    await ingest_market("NIE_ISTNIEJE", run_date=_RUN_DATE)

    result = await db_session.execute(
        select(IngestionRun).where(
            IngestionRun.market_code == "NIE_ISTNIEJE", IngestionRun.started_at >= before
        )
    )
    assert result.scalars().all() == []


async def test_ingest_market_concurrent_runs_only_one_executes_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Blokada doradcza (`app/db/advisory_lock.py`) musi faktycznie
    zablokować drugie równoległe uruchomienie dla tego samego
    `(market_code, run_date)` — i to bez czekania (`pg_try_advisory_lock`
    jest nieblokujące), stąd `asyncio.wait_for` z krótkim timeoutem: gdyby
    blokada czekała w nieskończoność zamiast od razu się wycofać, ten test
    sam by to złapał (timeout), zamiast zawiesić całe `pytest`.
    """
    calls: list[str] = []

    async def fake_run_ingestion(db: AsyncSession, *, market_code: str, run_date: date) -> None:
        calls.append(market_code)
        # Trzyma "pracę" wystarczająco długo, żeby drugie wywołanie na
        # pewno spróbowało wziąć blokadę, zanim pierwsze ją zwolni.
        await asyncio.sleep(0.3)

    monkeypatch.setattr(ingest_market_module, "_run_ingestion", fake_run_ingestion)

    lock_test_date = date(2031, 1, 15)  # unikalna data — osobny klucz blokady od innych testów

    await asyncio.wait_for(
        asyncio.gather(
            ingest_market("GPW", run_date=lock_test_date),
            ingest_market("GPW", run_date=lock_test_date),
        ),
        timeout=5,
    )

    assert calls == ["GPW"]
