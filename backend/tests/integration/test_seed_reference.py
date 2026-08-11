"""Testy `app.db.seed.seed_reference` (etap 8, krok zerowy — regresja).

Jeden test tu chroni konkretną rzecz, o którą krok zerowy rozbudował
komentarz w `seed.py` na kilkanaście linii: **dopisanie `ETFBW20TR` jako
benchmarku GPW nie może podmienić indeksu referencyjnego rynku**.
`INDEX_ASSETS` jest mapowane per rynek i dowiązywane do
`markets.index_asset_id`; gdyby benchmark trafił do tej samej krotki, panel
„Twoje rynki" (krok 34) po cichu zacząłby pokazywać ETF zamiast WIG20 —
zmiana widoczna dla użytkownika, wynikająca z pracy nad zupełnie innym
krokiem.

Drugi test pilnuje idempotencji: seed jest uruchamiany wielokrotnie (`make
seed`, `make prod-seed`, CI przed testami) i nie ma prawa duplikować aktywów
ani przestawiać już dowiązanych indeksów.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.seed import BENCHMARK_ASSETS, seed_reference
from app.modules.marketdata.models import Asset, Market

_GPW_INDEX_SYMBOL = "WIG20"
_US_INDEX_SYMBOL = "^GSPC"


async def test_seed_reference_keeps_market_index_not_benchmark(
    db_session: AsyncSession,
) -> None:
    """`markets.index_asset_id` wskazuje indeks rynku, nigdy benchmark."""
    await seed_reference(db_session)

    gpw = await db_session.get(Market, "GPW")
    us = await db_session.get(Market, "US")
    assert gpw is not None and gpw.index_asset_id is not None
    assert us is not None and us.index_asset_id is not None

    gpw_index = await db_session.get(Asset, gpw.index_asset_id)
    us_index = await db_session.get(Asset, us.index_asset_id)
    assert gpw_index is not None and gpw_index.symbol == _GPW_INDEX_SYMBOL
    assert us_index is not None and us_index.symbol == _US_INDEX_SYMBOL

    benchmark_symbols = {seed.symbol for seed in BENCHMARK_ASSETS}
    assert gpw_index.symbol not in benchmark_symbols, (
        "benchmark nie może zostać indeksem referencyjnym rynku — "
        "podmieniłby panel „Twoje rynki” z kroku 34"
    )


async def test_seed_reference_is_idempotent(db_session: AsyncSession) -> None:
    """Dwukrotny seed nie duplikuje aktywów ani nie przestawia indeksów."""
    await seed_reference(db_session)

    gpw_before = await db_session.get(Market, "GPW")
    assert gpw_before is not None
    index_before = gpw_before.index_asset_id

    benchmark_symbol = BENCHMARK_ASSETS[0].symbol
    count_before = await db_session.scalar(
        select(func.count()).select_from(Asset).where(Asset.symbol == benchmark_symbol)
    )
    assert count_before == 1, "benchmark musi istnieć po pierwszym seedzie"

    await seed_reference(db_session)
    db_session.expire_all()

    count_after = await db_session.scalar(
        select(func.count()).select_from(Asset).where(Asset.symbol == benchmark_symbol)
    )
    assert count_after == 1, "drugi seed zduplikował benchmark"

    gpw_after = await db_session.get(Market, "GPW")
    assert gpw_after is not None
    assert gpw_after.index_asset_id == index_before, "drugi seed przestawił indeks rynku"
