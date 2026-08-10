"""Testy repozytorium `app.modules.marketdata.repository` — `get_rate_pln`
(reguła `max(date) <= D`, CLAUDE.md #3.5), `upsert_fx_rates`, `upsert_prices`
(zapis idempotentny, CLAUDE.md #3.9), `get_latest_price` (ta sama reguła
`max(date) <= D` co `get_rate_pln`, ale dla `prices`) i `detect_price_jump`
(heurystyka nieskorygowanego splitu, plan krok 28) — plan krok 21/26/28,
etap 4/5.

Testy integracyjne (prawdziwa baza, jak `db_session`/`client` w
`conftest.py`), nie jednostkowe jak `tests/unit/test_nbp_provider.py` —
`get_rate_pln`/`upsert_*` to zapytania SQL, nie ma sensu ich mockować.
Dane testowe używają waluty spoza realnego słownika ISO (`ZZZ`) i
tymczasowego aktywa tworzonego/usuwanego per test, żeby sprzątanie nigdy
nie dotknęło danych seedowanych (`make seed`) ani innych testów.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest_asyncio
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.marketdata.models import Asset, FxRate, Price
from app.modules.marketdata.providers.base import FxQuote, PriceBar
from app.modules.marketdata.repository import (
    detect_price_jump,
    get_latest_price,
    get_rate_pln,
    upsert_fx_rates,
    upsert_prices,
)

_TEST_CURRENCY = "ZZZ"


@pytest_asyncio.fixture(autouse=True)
async def _cleanup_fx_rates(db_session: AsyncSession) -> AsyncGenerator[None, None]:
    yield
    await db_session.execute(delete(FxRate).where(FxRate.currency == _TEST_CURRENCY))
    await db_session.commit()


@pytest_asyncio.fixture
async def temp_asset(db_session: AsyncSession) -> AsyncGenerator[Asset, None]:
    """Aktywo tymczasowe (rynek `COMMODITY`, już w słowniku `markets`) tylko
    na czas jednego testu — `upsert_prices` wymaga istniejącego `asset_id`
    (FK `prices.asset_id -> assets.id`).
    """
    asset = Asset(
        symbol=f"TEST-{uuid.uuid4().hex[:8]}",
        name="Test Asset (tymczasowy, test repozytorium)",
        asset_class="commodity",
        market_code="COMMODITY",
        currency="PLN",
    )
    db_session.add(asset)
    await db_session.commit()
    await db_session.refresh(asset)
    yield asset
    await db_session.execute(delete(Price).where(Price.asset_id == asset.id))
    await db_session.execute(delete(Asset).where(Asset.id == asset.id))
    await db_session.commit()


async def test_upsert_fx_rates_on_conflict_overwrites_not_duplicates(
    db_session: AsyncSession,
) -> None:
    await upsert_fx_rates(
        db_session,
        [
            FxQuote(currency=_TEST_CURRENCY, date=date(2026, 7, 20), rate_pln=Decimal("4.0000")),
            FxQuote(currency=_TEST_CURRENCY, date=date(2026, 7, 21), rate_pln=Decimal("4.1000")),
        ],
    )

    # ponowne uruchomienie ingestii za ten sam dzień 2026-07-20 (idempotencja)
    await upsert_fx_rates(
        db_session,
        [FxQuote(currency=_TEST_CURRENCY, date=date(2026, 7, 20), rate_pln=Decimal("4.5555"))],
    )

    rate = await get_rate_pln(db_session, _TEST_CURRENCY, date(2026, 7, 20))
    assert rate == Decimal("4.5555")

    count = await db_session.scalar(
        select(func.count()).select_from(FxRate).where(FxRate.currency == _TEST_CURRENCY)
    )
    assert count == 2  # nadpisany wiersz, nie zduplikowany


async def test_upsert_fx_rates_with_empty_list_is_noop(db_session: AsyncSession) -> None:
    await upsert_fx_rates(db_session, [])

    count = await db_session.scalar(
        select(func.count()).select_from(FxRate).where(FxRate.currency == _TEST_CURRENCY)
    )
    assert count == 0


async def test_get_rate_pln_falls_back_to_latest_date_not_after_requested(
    db_session: AsyncSession,
) -> None:
    # 2026-07-17 piątek, 2026-07-18/19 weekend (brak notowania — celowo
    # pominięte), 2026-07-20 poniedziałek.
    await upsert_fx_rates(
        db_session,
        [
            FxQuote(currency=_TEST_CURRENCY, date=date(2026, 7, 17), rate_pln=Decimal("4.2000")),
            FxQuote(currency=_TEST_CURRENCY, date=date(2026, 7, 20), rate_pln=Decimal("4.3000")),
        ],
    )

    rate_saturday = await get_rate_pln(db_session, _TEST_CURRENCY, date(2026, 7, 18))
    assert rate_saturday == Decimal("4.2000")

    rate_sunday = await get_rate_pln(db_session, _TEST_CURRENCY, date(2026, 7, 19))
    assert rate_sunday == Decimal("4.2000")

    rate_exact = await get_rate_pln(db_session, _TEST_CURRENCY, date(2026, 7, 20))
    assert rate_exact == Decimal("4.3000")


async def test_get_rate_pln_returns_none_when_no_quote_on_or_before_date(
    db_session: AsyncSession,
) -> None:
    await upsert_fx_rates(
        db_session,
        [FxQuote(currency=_TEST_CURRENCY, date=date(2026, 7, 20), rate_pln=Decimal("4.0000"))],
    )

    rate = await get_rate_pln(db_session, _TEST_CURRENCY, date(2026, 7, 1))
    assert rate is None


async def test_get_rate_pln_returns_none_for_unknown_currency(db_session: AsyncSession) -> None:
    rate = await get_rate_pln(db_session, "XYZ", date(2026, 7, 20))
    assert rate is None


async def test_upsert_prices_skips_non_positive_close_adj_and_keeps_valid_rows(
    db_session: AsyncSession, temp_asset: Asset
) -> None:
    bars = [
        PriceBar(
            date=date(2026, 7, 20),
            open=Decimal("100"),
            high=Decimal("101"),
            low=Decimal("99"),
            close=Decimal("100.5"),
            close_adj=Decimal("100.5"),
            volume=1000,
        ),
        PriceBar(
            date=date(2026, 7, 21),
            open=None,
            high=None,
            low=None,
            close=None,
            close_adj=Decimal("0"),  # niepoprawne — CHECK close_adj_positive
            volume=None,
        ),
    ]

    await upsert_prices(db_session, temp_asset.id, bars)

    result = await db_session.execute(select(Price).where(Price.asset_id == temp_asset.id))
    rows = result.scalars().all()
    assert [row.date for row in rows] == [date(2026, 7, 20)]
    assert rows[0].close_adj == Decimal("100.5")


async def test_upsert_prices_on_conflict_overwrites_not_duplicates(
    db_session: AsyncSession, temp_asset: Asset
) -> None:
    await upsert_prices(
        db_session,
        temp_asset.id,
        [
            PriceBar(
                date=date(2026, 7, 20),
                open=Decimal("100"),
                high=Decimal("101"),
                low=Decimal("99"),
                close=Decimal("100.5"),
                close_adj=Decimal("100.5"),
                volume=1000,
            )
        ],
    )

    # ponowne uruchomienie joba EOD za ten sam dzień nadpisuje, nie duplikuje
    await upsert_prices(
        db_session,
        temp_asset.id,
        [
            PriceBar(
                date=date(2026, 7, 20),
                open=Decimal("100"),
                high=Decimal("103"),
                low=Decimal("99"),
                close=Decimal("102"),
                close_adj=Decimal("102"),
                volume=2000,
            )
        ],
    )

    result = await db_session.execute(select(Price).where(Price.asset_id == temp_asset.id))
    rows = result.scalars().all()
    assert len(rows) == 1
    assert rows[0].close_adj == Decimal("102")
    assert rows[0].volume == 2000


async def test_upsert_prices_records_source_and_defaults_to_null(
    db_session: AsyncSession, temp_asset: Asset
) -> None:
    """`source` zapisuje dostawcę wiersza; bez parametru zostaje `NULL`
    (tak jak wiersze sprzed migracji `926b382d1715`).
    """
    bar = PriceBar(
        date=date(2026, 7, 20),
        open=None,
        high=None,
        low=None,
        close=Decimal("100"),
        close_adj=Decimal("98"),
        volume=None,
    )

    await upsert_prices(db_session, temp_asset.id, [bar], source="yfinance")
    await upsert_prices(db_session, temp_asset.id, [replace(bar, date=date(2026, 7, 21))])

    result = await db_session.execute(
        select(Price).where(Price.asset_id == temp_asset.id).order_by(Price.date)
    )
    rows = result.scalars().all()
    assert [row.source for row in rows] == ["yfinance", None]


async def test_upsert_prices_on_conflict_overwrites_source_too(
    db_session: AsyncSession, temp_asset: Asset
) -> None:
    """Nadpisanie dnia zmienia też `source`.

    Sedno kolumny: yfinance oddaje realną cenę skorygowaną, Stooq wpisuje
    `close_adj := close`. Gdyby `ON CONFLICT` zostawiał stare `source`,
    seria po przełączeniu dostawcy twierdziłaby, że pochodzi z yfinance,
    niosąc wartości w konwencji Stooqa — a wtedy kolumna, która ma
    wykrywać wymieszane konwencje, sama by je maskowała.
    """
    bar = PriceBar(
        date=date(2026, 7, 20),
        open=None,
        high=None,
        low=None,
        close=Decimal("100"),
        close_adj=Decimal("98"),  # skorygowana ≠ close
        volume=None,
    )
    await upsert_prices(db_session, temp_asset.id, [bar], source="yfinance")

    # Stooq wraca do gry i nadpisuje ten sam dzień w swojej konwencji
    await upsert_prices(
        db_session,
        temp_asset.id,
        [replace(bar, close_adj=Decimal("100"))],
        source="stooq",
    )

    result = await db_session.execute(select(Price).where(Price.asset_id == temp_asset.id))
    rows = result.scalars().all()
    assert len(rows) == 1
    assert rows[0].source == "stooq"
    assert rows[0].close_adj == Decimal("100")


async def test_upsert_prices_with_empty_list_is_noop(
    db_session: AsyncSession, temp_asset: Asset
) -> None:
    await upsert_prices(db_session, temp_asset.id, [])

    result = await db_session.execute(select(Price).where(Price.asset_id == temp_asset.id))
    assert result.scalars().all() == []


async def test_get_latest_price_exact_match_on_requested_date(
    db_session: AsyncSession, temp_asset: Asset
) -> None:
    await upsert_prices(
        db_session,
        temp_asset.id,
        [
            PriceBar(
                date=date(2026, 7, 20),
                open=Decimal("100"),
                high=Decimal("101"),
                low=Decimal("99"),
                close=Decimal("100.5"),
                close_adj=Decimal("100.5"),
                volume=1000,
            )
        ],
    )

    price = await get_latest_price(db_session, temp_asset.id, date(2026, 7, 20))
    assert price is not None
    assert price.date == date(2026, 7, 20)
    assert price.close_adj == Decimal("100.5")


async def test_get_latest_price_falls_back_to_latest_date_not_after_requested(
    db_session: AsyncSession, temp_asset: Asset
) -> None:
    # 2026-07-17 piątek, notowanie; 2026-07-18/19 weekend (brak notowania —
    # celowo pominięte, tak jak w teście `get_rate_pln`).
    await upsert_prices(
        db_session,
        temp_asset.id,
        [
            PriceBar(
                date=date(2026, 7, 17),
                open=None,
                high=None,
                low=None,
                close=Decimal("100"),
                close_adj=Decimal("100"),
                volume=None,
            )
        ],
    )

    price = await get_latest_price(db_session, temp_asset.id, date(2026, 7, 19))
    assert price is not None
    assert price.date == date(2026, 7, 17)


async def test_get_latest_price_returns_none_when_no_row_on_or_before_date(
    db_session: AsyncSession, temp_asset: Asset
) -> None:
    await upsert_prices(
        db_session,
        temp_asset.id,
        [
            PriceBar(
                date=date(2026, 7, 20),
                open=None,
                high=None,
                low=None,
                close=Decimal("100"),
                close_adj=Decimal("100"),
                volume=None,
            )
        ],
    )

    price = await get_latest_price(db_session, temp_asset.id, date(2026, 7, 1))
    assert price is None


async def test_detect_price_jump_true_when_close_changes_more_than_threshold(
    db_session: AsyncSession, temp_asset: Asset
) -> None:
    # split 2:1 zasymulowany na surowym `close` (przepołowione), `close_adj`
    # celowo bez zmian — dokładnie ten przypadek, który heurystyka ma łapać.
    await upsert_prices(
        db_session,
        temp_asset.id,
        [
            PriceBar(
                date=date(2026, 7, 20),
                open=None,
                high=None,
                low=None,
                close=Decimal("100"),
                close_adj=Decimal("100"),
                volume=None,
            ),
            PriceBar(
                date=date(2026, 7, 21),
                open=None,
                high=None,
                low=None,
                close=Decimal("50"),
                close_adj=Decimal("100"),
                volume=None,
            ),
        ],
    )

    assert await detect_price_jump(db_session, temp_asset.id, date(2026, 7, 21)) is True


async def test_detect_price_jump_false_when_change_within_threshold(
    db_session: AsyncSession, temp_asset: Asset
) -> None:
    await upsert_prices(
        db_session,
        temp_asset.id,
        [
            PriceBar(
                date=date(2026, 7, 20),
                open=None,
                high=None,
                low=None,
                close=Decimal("100"),
                close_adj=Decimal("100"),
                volume=None,
            ),
            PriceBar(
                date=date(2026, 7, 21),
                open=None,
                high=None,
                low=None,
                close=Decimal("110"),
                close_adj=Decimal("110"),
                volume=None,
            ),
        ],
    )

    assert await detect_price_jump(db_session, temp_asset.id, date(2026, 7, 21)) is False


async def test_detect_price_jump_false_with_single_candle_in_history(
    db_session: AsyncSession, temp_asset: Asset
) -> None:
    await upsert_prices(
        db_session,
        temp_asset.id,
        [
            PriceBar(
                date=date(2026, 7, 20),
                open=None,
                high=None,
                low=None,
                close=Decimal("100"),
                close_adj=Decimal("100"),
                volume=None,
            )
        ],
    )

    assert await detect_price_jump(db_session, temp_asset.id, date(2026, 7, 20)) is False


async def test_detect_price_jump_false_when_one_row_has_null_close(
    db_session: AsyncSession, temp_asset: Asset
) -> None:
    await upsert_prices(
        db_session,
        temp_asset.id,
        [
            PriceBar(
                date=date(2026, 7, 20),
                open=None,
                high=None,
                low=None,
                close=None,
                close_adj=Decimal("100"),
                volume=None,
            ),
            PriceBar(
                date=date(2026, 7, 21),
                open=None,
                high=None,
                low=None,
                close=Decimal("150"),
                close_adj=Decimal("100"),
                volume=None,
            ),
        ],
    )

    assert await detect_price_jump(db_session, temp_asset.id, date(2026, 7, 21)) is False


async def test_detect_price_jump_false_when_no_rows(
    db_session: AsyncSession, temp_asset: Asset
) -> None:
    assert await detect_price_jump(db_session, temp_asset.id, date(2026, 7, 20)) is False


async def test_upsert_prices_with_all_invalid_bars_persists_nothing(
    db_session: AsyncSession, temp_asset: Asset
) -> None:
    await upsert_prices(
        db_session,
        temp_asset.id,
        [
            PriceBar(
                date=date(2026, 7, 20),
                open=None,
                high=None,
                low=None,
                close=None,
                close_adj=Decimal("-1"),
                volume=None,
            )
        ],
    )

    result = await db_session.execute(select(Price).where(Price.asset_id == temp_asset.id))
    assert result.scalars().all() == []
