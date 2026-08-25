"""Testy repozytorium stopy referencyjnej NBP (plan krok 41a, etap 8).

Integracyjne, nie jednostkowe — `get_reference_rate`/`list_reference_rates`
to zapytania SQL i lookup `max(effective_from) <= D`, a ich mockowanie
sprawdzałoby mocka, nie reguły (ta sama decyzja co w
`test_marketdata_repository.py`).

Tabela `nbp_reference_rates` nie ma FK ani właściciela, więc testy sprzątają
po sobie same: fixture czyści tabelę przed i po (`make seed` jej nie zasila
— wypełnia ją wyłącznie job workera).
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.marketdata.models import NbpReferenceRate
from app.modules.marketdata.providers.nbp_rates import ReferenceRate
from app.modules.marketdata.repository import (
    get_latest_reference_rate_date,
    get_reference_rate,
    list_reference_rates,
    upsert_reference_rates,
)

_FETCHED_AT = datetime(2026, 8, 25, 6, 20, tzinfo=UTC)

# Trzy realne decyzje RPP z nagranego archiwum NBP — daty i wartości nie są
# wymyślone, więc test jednocześnie dokumentuje, jak wygląda prawdziwa seria.
_HISTORY = [
    ReferenceRate(effective_from=date(2025, 11, 6), rate=Decimal("0.0425")),
    ReferenceRate(effective_from=date(2025, 12, 4), rate=Decimal("0.04")),
    ReferenceRate(effective_from=date(2026, 3, 5), rate=Decimal("0.0375")),
]


@pytest_asyncio.fixture
async def clean_rates(db_session: AsyncSession) -> AsyncGenerator[AsyncSession, None]:
    await db_session.execute(delete(NbpReferenceRate))
    await db_session.commit()
    yield db_session
    await db_session.execute(delete(NbpReferenceRate))
    await db_session.commit()


@pytest.mark.asyncio
async def test_lookup_returns_rate_in_force_on_date(clean_rates: AsyncSession) -> None:
    """`max(effective_from) <= D` — stopa obowiązuje do następnej decyzji."""
    await upsert_reference_rates(clean_rates, _HISTORY, source="nbp", fetched_at=_FETCHED_AT)

    # Dzień wejścia w życie: obowiązuje już nowa stopa (granica włączna).
    assert await get_reference_rate(clean_rates, date(2025, 12, 4)) == Decimal("0.04")
    # Dzień wcześniej: jeszcze poprzednia.
    assert await get_reference_rate(clean_rates, date(2025, 12, 3)) == Decimal("0.0425")
    # Środek okresu bez żadnej decyzji: cofamy się do ostatniej zmiany.
    assert await get_reference_rate(clean_rates, date(2026, 1, 15)) == Decimal("0.04")
    # Po ostatniej decyzji: stopa obowiązuje w nieskończoność w przód.
    assert await get_reference_rate(clean_rates, date(2026, 8, 25)) == Decimal("0.0375")


@pytest.mark.asyncio
async def test_lookup_before_first_entry_returns_none(clean_rates: AsyncSession) -> None:
    """Brak danych to `None`, nigdy zero.

    Zero jest poprawną stopą (RPP miała 0,10%, więc i 0% jest wyobrażalne),
    więc podstawienie go zamiast „nie wiem" dałoby Sharpe'a nie do odróżnienia
    od policzonego na prawdziwych danych.
    """
    await upsert_reference_rates(clean_rates, _HISTORY, source="nbp", fetched_at=_FETCHED_AT)

    assert await get_reference_rate(clean_rates, date(1997, 1, 1)) is None


@pytest.mark.asyncio
async def test_lookup_on_empty_table_returns_none(clean_rates: AsyncSession) -> None:
    assert await get_reference_rate(clean_rates, date(2026, 8, 25)) is None
    assert await get_latest_reference_rate_date(clean_rates) is None


@pytest.mark.asyncio
async def test_upsert_is_idempotent_and_updates_corrections(
    clean_rates: AsyncSession,
) -> None:
    """Powtórny przebieg nie duplikuje, a korekta wartości nadpisuje.

    Job pobiera pełne archiwum przy każdym uruchomieniu, więc idempotencja
    nie jest tu ozdobą — to warunek działania (CLAUDE.md #3.9).
    """
    await upsert_reference_rates(clean_rates, _HISTORY, source="nbp", fetched_at=_FETCHED_AT)
    await upsert_reference_rates(clean_rates, _HISTORY, source="nbp", fetched_at=_FETCHED_AT)

    count = len((await clean_rates.execute(select(NbpReferenceRate))).scalars().all())
    assert count == len(_HISTORY)

    corrected = [ReferenceRate(effective_from=date(2026, 3, 5), rate=Decimal("0.035"))]
    later = datetime(2026, 9, 1, 6, 20, tzinfo=UTC)
    await upsert_reference_rates(clean_rates, corrected, source="nbp", fetched_at=later)

    assert await get_reference_rate(clean_rates, date(2026, 3, 5)) == Decimal("0.035")
    assert len((await clean_rates.execute(select(NbpReferenceRate))).scalars().all()) == len(
        _HISTORY
    )


@pytest.mark.asyncio
async def test_upsert_empty_list_is_noop(clean_rates: AsyncSession) -> None:
    assert await upsert_reference_rates(clean_rates, [], source="nbp", fetched_at=_FETCHED_AT) == 0


@pytest.mark.asyncio
async def test_list_range_includes_rate_in_force_before_start(
    clean_rates: AsyncSession,
) -> None:
    """Okres zaczyna się w środku obowiązywania stopy — ten wpis musi być.

    Bez niego początek serii dziennej zostałby bez stopy wolnej od ryzyka,
    a Sharpe policzony na obciętej serii wyglądałby jak policzony na pełnej.
    """
    await upsert_reference_rates(clean_rates, _HISTORY, source="nbp", fetched_at=_FETCHED_AT)

    rates = await list_reference_rates(clean_rates, start=date(2026, 1, 1), end=date(2026, 6, 30))

    assert [r.effective_from for r in rates] == [date(2025, 12, 4), date(2026, 3, 5)]


@pytest.mark.asyncio
async def test_list_range_excludes_changes_after_end(clean_rates: AsyncSession) -> None:
    await upsert_reference_rates(clean_rates, _HISTORY, source="nbp", fetched_at=_FETCHED_AT)

    rates = await list_reference_rates(clean_rates, start=date(2025, 11, 1), end=date(2025, 12, 31))

    assert [r.effective_from for r in rates] == [date(2025, 11, 6), date(2025, 12, 4)]


@pytest.mark.asyncio
async def test_latest_date_reflects_last_decision(clean_rates: AsyncSession) -> None:
    """Świeżość liczymy z `max(effective_from)`, nie z `data_publikacji` XML-a."""
    await upsert_reference_rates(clean_rates, _HISTORY, source="nbp", fetched_at=_FETCHED_AT)

    assert await get_latest_reference_rate_date(clean_rates) == date(2026, 3, 5)
