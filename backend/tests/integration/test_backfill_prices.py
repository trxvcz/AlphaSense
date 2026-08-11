"""Testy `worker.jobs.backfill_prices` (etap 8, krok zerowy).

Integracyjne (prawdziwa baza, jak `test_ingest_market.py`), zero sieci —
`build_fallback_chain`/`list_active_assets` podmieniane na atrybutach modułu
`worker.jobs.ingest_market`, bo to tam zostały zaimportowane (konwencja
„where to patch" z `test_ingest_market.py`).

Ten plik pilnuje przede wszystkim **raportu**, nie zapisu. Powód jest
historyczny i konkretny: pierwsza wersja licznika liczyła okna, w których
dostawca odpowiedział, i pokazała „WIG20: 5 okien" przy jednym wierszu w
bazie. Poprawka przeszła na stan bazy — i kłamała dalej, tylko subtelniej,
bo aktywo z historią sprzed przebiegu raportuje komplet także wtedy, gdy
każde okno padło. To ta sama klasa błędu co „test przechodzi, ale niczego
nie sprawdza": raport wygląda na sukces i nim nie jest.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator, Awaitable, Callable
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

import worker.jobs.ingest_market as ingest_market_module
from app.modules.marketdata.models import Asset, AssetSourceMap, Price
from app.modules.marketdata.providers.base import Capability, PriceBar
from worker.jobs.ingest_market import backfill_prices

_START = date(2026, 6, 1)
_END = date(2026, 6, 30)


@dataclass
class _FakeProvider:
    """Duck-typed odpowiednik `Guarded` (jak w `test_ingest_market.py`),
    plus licznik wywołań — kilka testów pyta nie „co zwrócił", tylko „ile
    razy go w ogóle zapytano"."""

    name: str
    supports: set[Capability]
    ohlcv_by_symbol: dict[str, list[PriceBar] | Exception] = field(default_factory=dict)
    calls: list[tuple[str, date, date]] = field(default_factory=list)

    async def get_ohlcv(self, symbol: str, start: date, end: date) -> list[PriceBar]:
        self.calls.append((symbol, start, end))
        result = self.ohlcv_by_symbol.get(symbol, [])
        if isinstance(result, Exception):
            raise result
        return result

    async def get_metadata(self, symbol: str) -> None:
        return None


def _returning(value: Any) -> Callable[..., Awaitable[Any]]:
    async def _fn(*_args: Any, **_kwargs: Any) -> Any:
        return value

    return _fn


def _bar(day: date, *, close: str = "100", close_adj: str | None = None) -> PriceBar:
    return PriceBar(
        date=day,
        open=None,
        high=None,
        low=None,
        close=Decimal(close),
        close_adj=Decimal(close_adj if close_adj is not None else close),
        volume=None,
    )


@pytest_asyncio.fixture
async def temp_assets(db_session: AsyncSession) -> AsyncGenerator[list[Asset], None]:
    """Dwa tymczasowe aktywa na `GPW` — drugie jest potrzebne, żeby dało się
    sprawdzić, że porażka pierwszego nie zabija reszty przebiegu."""
    assets = []
    for index in range(2):
        asset = Asset(
            symbol=f"BF{index}{uuid.uuid4().hex[:6]}",
            name=f"Test Backfill Asset {index}",
            asset_class="equity",
            market_code="GPW",
            currency="PLN",
        )
        db_session.add(asset)
        assets.append(asset)
    await db_session.commit()
    for asset in assets:
        await db_session.refresh(asset)

    yield assets

    ids = [a.id for a in assets]
    await db_session.execute(delete(Price).where(Price.asset_id.in_(ids)))
    await db_session.execute(delete(AssetSourceMap).where(AssetSourceMap.asset_id.in_(ids)))
    await db_session.execute(delete(Asset).where(Asset.id.in_(ids)))
    await db_session.commit()


async def _map_source(db: AsyncSession, asset: Asset, provider: str, symbol: str) -> None:
    db.add(AssetSourceMap(asset_id=asset.id, provider=provider, provider_symbol=symbol, priority=1))
    await db.commit()


async def test_counter_reports_new_rows_not_preexisting_ones(
    db_session: AsyncSession, temp_assets: list[Asset], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Aktywo z historią sprzed przebiegu + dostawca oddający pustkę.

    To dokładnie scenariusz, w którym poprzedni licznik raportował sukces:
    trzy wiersze leżały w bazie od wcześniej, backfill nie przyniósł nic, a
    raport pokazywał „3 notowania".
    """
    asset = temp_assets[0]
    for day in (date(2026, 6, 2), date(2026, 6, 3), date(2026, 6, 4)):
        db_session.add(
            Price(asset_id=asset.id, date=day, close=Decimal("10"), close_adj=Decimal("10"))
        )
    await db_session.commit()

    fake = _FakeProvider("fake", {Capability.OHLCV}, ohlcv_by_symbol={"SYM": []})
    monkeypatch.setattr(ingest_market_module, "build_fallback_chain", lambda _code: [fake])
    monkeypatch.setattr(ingest_market_module, "list_active_assets", _returning([asset]))
    await _map_source(db_session, asset, "fake", "SYM")

    targets = await backfill_prices(db_session, start=_START, end=_END, market_codes=["GPW"])

    assert len(targets) == 1
    target = targets[0]
    assert target.rows_added == 0, "nic nie przyszło, więc delta musi być zerowa"
    assert target.rows_before == 3
    assert target.rows_after == 3
    assert not target.is_empty, "wiersze w bazie są — tylko nie z tego przebiegu"


async def test_target_without_any_data_is_still_reported(
    db_session: AsyncSession, temp_assets: list[Asset], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Cel z zerem wierszy nie znika z raportu — „których brakuje" jest
    ważniejsze niż lista tych, które się udały."""
    asset = temp_assets[0]
    fake = _FakeProvider("fake", {Capability.OHLCV}, ohlcv_by_symbol={"SYM": []})
    monkeypatch.setattr(ingest_market_module, "build_fallback_chain", lambda _code: [fake])
    monkeypatch.setattr(ingest_market_module, "list_active_assets", _returning([asset]))
    await _map_source(db_session, asset, "fake", "SYM")

    targets = await backfill_prices(db_session, start=_START, end=_END, market_codes=["GPW"])

    assert [t.label for t in targets] == [asset.symbol]
    assert targets[0].is_empty
    assert targets[0].rows_added == 0


async def test_failing_asset_does_not_stop_the_rest(
    db_session: AsyncSession, temp_assets: list[Asset], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Skill `job-eod`, reguła 6 — błąd jednego celu nie przerywa przebiegu."""
    broken, healthy = temp_assets
    fake = _FakeProvider(
        "fake",
        {Capability.OHLCV},
        ohlcv_by_symbol={
            "BROKEN": RuntimeError("dostawca zwrócił śmieci"),
            "HEALTHY": [_bar(date(2026, 6, 15))],
        },
    )
    monkeypatch.setattr(ingest_market_module, "build_fallback_chain", lambda _code: [fake])
    monkeypatch.setattr(ingest_market_module, "list_active_assets", _returning([broken, healthy]))
    await _map_source(db_session, broken, "fake", "BROKEN")
    await _map_source(db_session, healthy, "fake", "HEALTHY")

    targets = await backfill_prices(db_session, start=_START, end=_END, market_codes=["GPW"])

    by_label = {t.label: t for t in targets}
    assert by_label[broken.symbol].is_empty
    assert by_label[broken.symbol].windows_failed == 1
    assert by_label[healthy.symbol].rows_added == 1


async def test_unavailable_provider_stops_windows_and_is_flagged(
    db_session: AsyncSession, temp_assets: list[Asset], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Brak mapowania w `asset_source_map` → `ProviderUnavailableError`.

    Kolejne okna padłyby tak samo, a każda próba dobija `CircuitBreaker`.
    Przebieg ma przerwać pętlę po pierwszym takim oknie i **odróżnić** ten
    stan od „dostawca odpowiedział pustką" — to dwie różne diagnozy.
    """
    asset = temp_assets[0]
    fake = _FakeProvider("fake", {Capability.OHLCV})
    monkeypatch.setattr(ingest_market_module, "build_fallback_chain", lambda _code: [fake])
    monkeypatch.setattr(ingest_market_module, "list_active_assets", _returning([asset]))
    # świadomie BEZ `_map_source` — dostawca nie ma symbolu dla tego aktywa

    targets = await backfill_prices(
        db_session, start=date(2021, 1, 1), end=date(2026, 1, 1), market_codes=["GPW"]
    )

    assert len(targets) == 1
    target = targets[0]
    assert target.unavailable, "brak dostawcy to nie to samo co brak danych"
    assert target.windows_total > 1, "zakres 5-letni musi dać kilka okien"
    assert target.windows_failed == target.windows_total, "wszystkie okna liczone jako nieudane"
    assert fake.calls == [], "bez mapowania nie ma czego pytać — zero zapytań"


async def test_provider_pinning_skips_other_providers(
    db_session: AsyncSession, temp_assets: list[Asset], monkeypatch: pytest.MonkeyPatch
) -> None:
    """`provider=` przypina backfill do jednego dostawcy.

    Bez tego łańcuch rozstrzyga się per okno i potrafi zszyć w jedną serię
    dwie niekompatybilne konwencje `close_adj`.
    """
    asset = temp_assets[0]
    first = _FakeProvider("stooq", {Capability.OHLCV}, ohlcv_by_symbol={"SYM": [_bar(_START)]})
    second = _FakeProvider(
        "yfinance",
        {Capability.OHLCV},
        ohlcv_by_symbol={"SYM": [_bar(date(2026, 6, 15), close="100", close_adj="98")]},
    )
    monkeypatch.setattr(ingest_market_module, "build_fallback_chain", lambda _code: [first, second])
    monkeypatch.setattr(ingest_market_module, "list_active_assets", _returning([asset]))
    await _map_source(db_session, asset, "stooq", "SYM")
    await _map_source(db_session, asset, "yfinance", "SYM")

    targets = await backfill_prices(
        db_session, start=_START, end=_END, market_codes=["GPW"], provider="yfinance"
    )

    assert first.calls == [], "przypięty dostawca to jedyny, którego wolno pytać"
    assert second.calls, "przypięty dostawca musi zostać zapytany"
    assert targets[0].rows_added == 1
    diagnostics = targets[0].diagnostics
    assert diagnostics is not None
    assert diagnostics.sources == ("yfinance",)


async def test_mixed_close_adj_convention_is_detected(
    db_session: AsyncSession, temp_assets: list[Asset], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Blokujące znalezisko #1: seria z dwiema konwencjami `close_adj`.

    Wiersz nieskorygowany (`close_adj == close`, konwencja Stooq/Finnhub/
    Binance) obok skorygowanego (`close_adj != close`, yfinance) — na styku
    powstaje skok niewidoczny w surowym `close`.
    """
    asset = temp_assets[0]
    db_session.add(
        Price(
            asset_id=asset.id,
            date=date(2026, 6, 2),
            close=Decimal("100"),
            close_adj=Decimal("100"),
            source="stooq",
        )
    )
    await db_session.commit()

    fake = _FakeProvider(
        "yfinance",
        {Capability.OHLCV},
        ohlcv_by_symbol={"SYM": [_bar(date(2026, 6, 3), close="100", close_adj="98")]},
    )
    monkeypatch.setattr(ingest_market_module, "build_fallback_chain", lambda _code: [fake])
    monkeypatch.setattr(ingest_market_module, "list_active_assets", _returning([asset]))
    await _map_source(db_session, asset, "yfinance", "SYM")

    targets = await backfill_prices(db_session, start=_START, end=_END, market_codes=["GPW"])

    diagnostics = targets[0].diagnostics
    assert diagnostics is not None
    assert diagnostics.mixed_convention, "jedna seria, dwie konwencje — musi być wykryte"
    assert diagnostics.adjusted_rows == 1
    assert diagnostics.unadjusted_rows == 1
    assert diagnostics.mixed_sources
    assert set(diagnostics.sources) == {"stooq", "yfinance"}


async def test_symbol_filter_narrows_targets(
    db_session: AsyncSession, temp_assets: list[Asset], monkeypatch: pytest.MonkeyPatch
) -> None:
    wanted, other = temp_assets
    fake = _FakeProvider("fake", {Capability.OHLCV}, ohlcv_by_symbol={"SYM": [_bar(_START)]})
    monkeypatch.setattr(ingest_market_module, "build_fallback_chain", lambda _code: [fake])
    monkeypatch.setattr(ingest_market_module, "list_active_assets", _returning([wanted, other]))
    await _map_source(db_session, wanted, "fake", "SYM")

    targets = await backfill_prices(
        db_session, start=_START, end=_END, market_codes=["GPW"], symbols=[wanted.symbol.lower()]
    )

    assert [t.label for t in targets] == [wanted.symbol], "filtr symboli ignoruje wielkość liter"


async def test_reversed_range_is_rejected(db_session: AsyncSession) -> None:
    with pytest.raises(ValueError, match="jest po"):
        await backfill_prices(db_session, start=_END, end=_START, market_codes=["GPW"])
