"""Logika modułu `dividends` — kalendarz dla portfela (plan krok 47, etap 9).

Warstwa serwisu zgodnie z CLAUDE.md §8: `routes` waliduje i autoryzuje,
tutaj jest logika, SQL siedzi w `repository.py`.
"""

from __future__ import annotations

from datetime import date as date_
from datetime import timedelta
from decimal import Decimal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.dividends import repository
from app.modules.dividends.schemas import DividendCalendarOut, DividendEventOut

# Dostawca, którego mapowanie w `asset_source_map` rozstrzyga o pokryciu
# kalendarza. Stała tutaj, a nie w `repository`, bo to decyzja produktowa
# („czym dziś pokrywamy dywidendy"), nie szczegół zapytania.
DIVIDEND_PROVIDER = "alphavantage"


async def portfolio_calendar(
    db: AsyncSession,
    portfolio_id: UUID,
    *,
    today: date_,
    horizon_days: int = 90,
) -> DividendCalendarOut:
    """Najbliższe ex-daty dla pozycji z portfela, wraz z zasięgiem danych.

    **Izolacja danych nie dzieje się tutaj.** `portfolio_id` przychodzi
    z `get_owned_portfolio`, który już zweryfikował własność (ADR-002,
    skill `izolacja-danych`) — ta funkcja nigdy nie jest wołana z surowym
    identyfikatorem z żądania. Zdarzenia dywidendowe same w sobie nie są
    prywatne; prywatna jest wyłącznie informacja o tym, **czyje pozycje**
    wyznaczyły ten kalendarz i jakie mają wielkości.

    **Okno zaczyna się dziś, nie wczoraj.** Zdarzenie z wczorajszą ex-datą
    jest już nie do złapania, a pokazane w kalendarzu „nadchodzących"
    sugerowałoby, że jeszcze coś da się z nim zrobić. Historia wypłat to
    inny ekran i inny zakres (Etap 21).

    Ilości sumujemy per aktywo: jedno aktywo bywa w portfelu w kilku
    wierszach `holdings` (różne `valid_from`, różne noty), a dywidendę
    dostaje się od łącznej liczby akcji, nie od wiersza w naszej bazie.
    """
    positions = await repository.list_portfolio_positions(db, portfolio_id)
    if not positions:
        return DividendCalendarOut(
            items=[],
            horizon_days=horizon_days,
            assets_covered=0,
            assets_without_coverage=[],
            uncovered_markets=[],
        )

    quantities: dict[UUID, Decimal] = {}
    symbols: dict[UUID, str] = {}
    markets: dict[UUID, str] = {}
    for asset_id, symbol, market_code, _currency, quantity in positions:
        quantities[asset_id] = quantities.get(asset_id, Decimal(0)) + quantity
        symbols[asset_id] = symbol
        markets[asset_id] = market_code

    covered = await repository.list_covered_asset_ids(db, DIVIDEND_PROVIDER)
    covered_in_portfolio = {asset_id for asset_id in quantities if asset_id in covered}
    without_coverage = sorted(
        symbol for asset_id, symbol in symbols.items() if asset_id not in covered
    )
    # Rynek trafia na listę „nieobjętych" dopiero wtedy, gdy ŻADNE aktywo
    # portfela z tego rynku nie ma pokrycia. Inaczej jeden nieobsłużony
    # walor kazałby napisać „nie pokrywamy GPW" komuś, kto dostaje z GPW
    # komplet danych — a to zdanie ma być prawdziwe, nie ostrożne.
    markets_with_coverage = {markets[asset_id] for asset_id in covered_in_portfolio}
    uncovered_markets = sorted(set(markets.values()) - markets_with_coverage)

    events = await repository.list_upcoming_events(
        db,
        list(quantities),
        date_from=today,
        date_to=today + timedelta(days=horizon_days),
    )

    items = [
        DividendEventOut(
            symbol=symbols[event.asset_id],
            market_code=markets[event.asset_id],
            ex_date=event.ex_date,
            record_date=event.record_date,
            pay_date=event.pay_date,
            declaration_date=event.declaration_date,
            amount_per_share=event.amount,
            currency=event.currency,
            quantity=quantities[event.asset_id],
            estimated_gross=event.amount * quantities[event.asset_id],
            source=event.source,
            fetched_at=event.fetched_at,
        )
        for event in events
    ]

    return DividendCalendarOut(
        items=items,
        horizon_days=horizon_days,
        assets_covered=len(covered_in_portfolio),
        assets_without_coverage=without_coverage,
        uncovered_markets=uncovered_markets,
    )
