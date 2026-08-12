"""Zapytania SQLAlchemy modułu `portfolio`: CRUD `Portfolio`/`Holding` i
odczyt `PortfolioValuation` (plan kroki 25-28, etap 5).

Świadomie **bez** tłumaczenia wyjątków domenowych tutaj (skill
`fastapi-modul`: repository = SQLAlchemy/zapytania, nie logika biznesowa) —
np. naruszenie `UNIQUE(portfolio_id, asset_id)` przy `create_holding`
podnosi surowy `IntegrityError` z SQLAlchemy, `service.py` go łapie i
tłumaczy na `ConflictError`.

Każda mutacja `holdings` (`create_holding`/`update_holding_row`/
`delete_holding`) bumpuje `Portfolio.holdings_version`/`holdings_changed_at`
w tej samej transakcji (jeden `commit()`) — worker snapshotów EOD (plan
krok 27, poza zakresem tego modułu) czyta `holdings_changed_at`, żeby
ustawić `PortfolioValuation.composition_change`.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date as date_
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.marketdata.models import Asset, Price
from app.modules.portfolio.models import Holding, Portfolio, PortfolioValuation

# `?range=` w `GET /valuations` — liczba miesięcy do odjęcia od „dziś" dla
# zakresów kalendarzowych (YTD/max liczone osobno, patrz `_range_start`).
_RANGE_MONTHS: dict[str, int] = {"1M": 1, "3M": 3, "1Y": 12}


async def list_portfolios(db: AsyncSession, *, user_id: UUID) -> list[Portfolio]:
    """Portfele użytkownika, posortowane od najstarszego — **zawsze**
    filtrowane po `user_id` (skill `izolacja-danych`: „zapytania listujące
    filtrują po user_id, nie polegaj na nieodgadywalności ID").
    """
    stmt = select(Portfolio).where(Portfolio.user_id == user_id).order_by(Portfolio.created_at)
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def list_all_portfolios(db: AsyncSession) -> list[Portfolio]:
    """Wszystkie portfele w systemie, bez filtra `user_id` — wyłącznie do
    użytku workera snapshotów EOD (`worker/jobs/snapshot_portfolios.py`,
    plan krok 27), który wycenia każdy portfel niezależnie od właściciela;
    nigdy z `routes.py` (patrz `list_portfolios` wyżej dla ścieżki
    dotykającej żądania HTTP, tam filtr po `user_id` jest obowiązkowy, skill
    `izolacja-danych`).

    Sortowanie po `id` (nie `created_at` jak `list_portfolios`) tylko po to,
    żeby logi joba miały deterministyczną kolejność między przebiegami —
    porządek biznesowo nieistotny dla tej funkcji.
    """
    stmt = select(Portfolio).order_by(Portfolio.id)
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def create_portfolio(db: AsyncSession, *, user_id: UUID, name: str, type_: str) -> Portfolio:
    portfolio = Portfolio(user_id=user_id, name=name, type=type_)
    db.add(portfolio)
    await db.commit()
    await db.refresh(portfolio)
    return portfolio


async def update_portfolio(
    db: AsyncSession, portfolio: Portfolio, *, name: str | None, type_: str | None
) -> Portfolio:
    """Aktualizuje tylko pola, które przyszły nie-`None` (patrz docstring
    `schemas.PortfolioUpdateIn` — `None` == „bez zmian" dla tych dwóch
    kolumn `NOT NULL`)."""
    if name is not None:
        portfolio.name = name
    if type_ is not None:
        portfolio.type = type_
    await db.commit()
    await db.refresh(portfolio)
    return portfolio


async def delete_portfolio(db: AsyncSession, portfolio: Portfolio) -> None:
    """Kaskaduje na `holdings`/`portfolio_valuations` przez `ON DELETE
    CASCADE` już zdefiniowane w bazie (`models.py`) — nie ORM cascade."""
    await db.delete(portfolio)
    await db.commit()


async def get_asset(db: AsyncSession, asset_id: UUID) -> Asset | None:
    """Lookup po kluczu głównym — używane przy tworzeniu/wycenie pozycji do
    sprawdzenia, że `asset_id` odnosi się do istniejącego aktywa, i do
    odczytania jego `symbol`/`currency`."""
    return await db.get(Asset, asset_id)


async def get_portfolio_by_id(db: AsyncSession, portfolio_id: UUID) -> Portfolio | None:
    """Lookup bez weryfikacji właściciela — wyłącznie do wewnętrznej
    orkiestracji `service.py` (np. odnalezienie portfela nadrzędnego dla
    `Holding` już zweryfikowanego przez `get_owned_holding`), nigdy
    bezpośrednio z `routes.py` (patrz `core/deps.get_owned_portfolio` dla
    ścieżki dotykającej żądania HTTP)."""
    return await db.get(Portfolio, portfolio_id)


@dataclass(frozen=True, slots=True)
class HeldAssetPriceCoverage:
    """Od kiedy wycena WSZYSTKICH trzymanych pozycji jest możliwa.

    Silnik wyceny (`worker/jobs/snapshot_portfolios.py`) pomija pozycję bez
    ceny, zamiast liczyć ją jako zero — poprawnie, bo zero byłoby kłamstwem.
    Skutek uboczny: dla dnia sprzed debiutu jednej pozycji snapshot i tak
    powstanie, tylko cząstkowy, a w `portfolio_valuations` (append-only,
    ADR-101) nie da się go potem odróżnić od pełnego. Stąd guard w
    `seed-history`, a nie sprzątanie po fakcie.
    """

    first_full_date: date_ | None
    assets_without_prices: tuple[str, ...]

    @property
    def is_complete(self) -> bool:
        return not self.assets_without_prices and self.first_full_date is not None


async def held_asset_price_coverage(db: AsyncSession) -> HeldAssetPriceCoverage:
    """Pokrycie cenami aktywów faktycznie trzymanych w jakimkolwiek portfelu.

    `first_full_date` to **maksimum z minimów** per aktywo, nie globalne
    `MIN(prices.date)`: pełne pokrycie zaczyna się dopiero tam, gdzie ma już
    dane pozycja o najpóźniejszym debiucie. Globalne minimum przepuściłoby
    dokładnie te dni, przed którymi guard ma chronić.

    Aktywa spoza portfeli są pomijane — jeden nienotowany walor w słowniku
    `assets` nie może blokować `seed-history` wszystkim.
    """
    held = select(Holding.asset_id).distinct().subquery()
    stmt = (
        select(Asset.symbol, func.min(Price.date))
        .select_from(held)
        .join(Asset, Asset.id == held.c.asset_id)
        .outerjoin(Price, Price.asset_id == held.c.asset_id)
        .group_by(Asset.symbol)
    )
    rows = (await db.execute(stmt)).all()

    missing = tuple(sorted(symbol for symbol, first in rows if first is None))
    firsts = [first for _, first in rows if first is not None]
    return HeldAssetPriceCoverage(
        # Przy choćby jednym aktywie bez cen dzień pełnego pokrycia nie
        # istnieje w ogóle — `max()` z pozostałych byłby wtedy datą, przed
        # którą pokrycie i tak nie jest pełne, czyli fałszywym zielonym.
        first_full_date=max(firsts) if firsts and not missing else None,
        assets_without_prices=missing,
    )


def bump_holdings_version(portfolio: Portfolio, *, changed_at: date_) -> None:
    """Inkrementuje `holdings_version` i ustawia `holdings_changed_at`.

    Czysta mutacja atrybutów obiektu już śledzonego przez sesję — wołający
    commituje (ta funkcja nie robi tego sama), żeby bump zawsze trafiał do
    tej samej transakcji co mutacja `holdings`, którą sygnalizuje.
    """
    portfolio.holdings_version += 1
    portfolio.holdings_changed_at = changed_at


async def list_holdings_with_assets(
    db: AsyncSession, portfolio_id: UUID
) -> list[tuple[Holding, Asset]]:
    """Pozycje portfela razem z ich `Asset` (`JOIN`, nie N+1) — `symbol`/
    `currency` potrzebne do wyceny i do `HoldingOut.symbol`."""
    stmt = (
        select(Holding, Asset)
        .join(Asset, Holding.asset_id == Asset.id)
        .where(Holding.portfolio_id == portfolio_id)
        .order_by(Asset.symbol)
    )
    result = await db.execute(stmt)
    return [(holding, asset) for holding, asset in result.all()]


async def create_holding(
    db: AsyncSession,
    portfolio: Portfolio,
    *,
    asset_id: UUID,
    quantity: Decimal,
    avg_cost: Decimal | None,
    cost_currency: str | None,
    note: str | None,
    changed_at: date_,
) -> Holding:
    """Dodaje pozycję i bumpuje `holdings_version` portfela w jednej
    transakcji. Naruszenie `UNIQUE(portfolio_id, asset_id)` podnosi
    `IntegrityError` przy `commit()` — łapie i tłumaczy `service.py`.
    """
    holding = Holding(
        portfolio_id=portfolio.id,
        asset_id=asset_id,
        quantity=quantity,
        avg_cost=avg_cost,
        cost_currency=cost_currency,
        note=note,
    )
    db.add(holding)
    bump_holdings_version(portfolio, changed_at=changed_at)
    await db.commit()
    await db.refresh(holding)
    return holding


async def update_holding_row(
    db: AsyncSession, portfolio: Portfolio, holding: Holding, *, changed_at: date_
) -> Holding:
    """Commituje zmiany już naniesione na `holding` przez `service.py`
    razem z bumpem `holdings_version` portfela nadrzędnego — jedna
    transakcja, jak wymaga kontrakt kroku 26."""
    bump_holdings_version(portfolio, changed_at=changed_at)
    await db.commit()
    await db.refresh(holding)
    return holding


async def delete_holding(
    db: AsyncSession, portfolio: Portfolio, holding: Holding, *, changed_at: date_
) -> None:
    """Twardy `DELETE` (decyzja produktowa: `Holding` to bieżący stan, nie
    historia — ADR-101 „append-only" dotyczy wyłącznie
    `portfolio_valuations`), z bumpem `holdings_version` w tej samej
    transakcji."""
    await db.delete(holding)
    bump_holdings_version(portfolio, changed_at=changed_at)
    await db.commit()


async def get_previous_valuation(
    db: AsyncSession, portfolio_id: UUID, *, before: date_
) -> PortfolioValuation | None:
    """Najnowszy snapshot **ściśle przed** `before` — podstawa `change_1d`
    (`GET /summary`). `before` to zwykle „dziś" (D), bo worker mógł
    jeszcze nie zapisać snapshotu za dzisiaj w momencie wywołania live."""
    stmt = (
        select(PortfolioValuation)
        .where(PortfolioValuation.portfolio_id == portfolio_id, PortfolioValuation.date < before)
        .order_by(PortfolioValuation.date.desc())
        .limit(1)
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def get_first_valuation_since(
    db: AsyncSession, portfolio_id: UUID, *, since: date_
) -> PortfolioValuation | None:
    """Najstarszy snapshot **od** `since` (włącznie) — podstawa
    `change_ytd` (`since` = 1 stycznia bieżącego roku)."""
    stmt = (
        select(PortfolioValuation)
        .where(PortfolioValuation.portfolio_id == portfolio_id, PortfolioValuation.date >= since)
        .order_by(PortfolioValuation.date.asc())
        .limit(1)
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


def _subtract_months(d: date_, months: int) -> date_:
    """Odejmuje `months` miesięcy kalendarzowych od `d` (bez `dateutil` —
    nowa zależność wymagałaby zgody użytkownika, CLAUDE.md #10); dzień
    docinany do ostatniego dnia docelowego miesiąca (`calendar.monthrange`),
    żeby np. 31 marca − 1 miesiąc nie wywaliło się na „31 lutego"."""
    month_index = d.month - 1 - months
    year = d.year + month_index // 12
    month = month_index % 12 + 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return date_(year, month, day)


def _range_start(range_: str, today: date_) -> date_ | None:
    """Dolna granica daty dla `range_` (`1M`/`3M`/`1Y`/`YTD`/`max`) —
    `None` dla `max` (bez dolnej granicy, cała historia)."""
    if range_ == "YTD":
        return date_(today.year, 1, 1)
    if range_ == "max":
        return None
    return _subtract_months(today, _RANGE_MONTHS[range_])


async def list_valuations(
    db: AsyncSession, portfolio_id: UUID, *, range_: str, today: date_
) -> list[PortfolioValuation]:
    """Seria `portfolio_valuations` w `range_`, posortowana rosnąco po
    dacie (kontrakt `GET /valuations`, plan krok 26)."""
    start = _range_start(range_, today)
    stmt = select(PortfolioValuation).where(PortfolioValuation.portfolio_id == portfolio_id)
    if start is not None:
        stmt = stmt.where(PortfolioValuation.date >= start)
    stmt = stmt.order_by(PortfolioValuation.date.asc())
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def valuations_marker(db: AsyncSession, portfolio_id: UUID) -> str:
    """Segment klucza cache dla wyników liczonych z `portfolio_valuations`
    (`MAX(date)` i `COUNT(*)`, plan krok 40).

    **`MAX(date)` samo nie wystarczy** — inaczej niż `_eod_marker` w
    `analytics.service`, który pilnuje danych rynkowych przyrastających
    wyłącznie od najnowszej strony. Tutaj wiersze przybywają też WSTECZ:
    `seed-history` (krok zerowy etapu 8) dopisuje pełne lata historii, nie
    ruszając maksimum. Sam `MAX` dałby po takim przebiegu trafienie w cache
    ze zwrotem policzonym z poprzedniej, krótszej serii — czyli błędną liczbę
    podaną z pełnym przekonaniem, do wygaśnięcia TTL.

    `COUNT(*)` domyka też usunięcie wiersza. Nie domyka nadpisania `value_pln`
    za istniejący dzień przy tej samej liczbie wierszy (powtórka joba EOD za
    ten sam dzień) — na to jest TTL, ten sam kompromis co w kroku 31.
    Deterministyczne `"none"` dla portfela bez historii.
    """
    stmt = select(func.max(PortfolioValuation.date), func.count()).where(
        PortfolioValuation.portfolio_id == portfolio_id
    )
    latest, count = (await db.execute(stmt)).one()
    if latest is None:
        return "none"
    return f"{latest.isoformat()}:{count}"


async def upsert_valuation(
    db: AsyncSession,
    *,
    portfolio_id: UUID,
    date: date_,
    value_pln: Decimal,
    composition_change: bool,
) -> None:
    """Zapisuje snapshot `portfolio_valuations`, idempotentnie (`ON CONFLICT
    (portfolio_id, date) DO UPDATE`) — ponowne uruchomienie joba snapshotów
    EOD (`worker/jobs/snapshot_portfolios.py`, plan krok 27) za ten sam
    dzień nadpisuje `value_pln`/`composition_change`, nie duplikuje wiersza
    (CLAUDE.md #3.9, SKILL `job-eod` reguła 4) — dokładnie ten sam wzorzec co
    `upsert_prices`/`upsert_fx_rates` w `app/modules/marketdata/repository.py`.

    Commituje sama (jak `upsert_*` w `marketdata`) — wołający nie musi
    otwierać osobnej transakcji per portfel.
    """
    stmt = insert(PortfolioValuation).values(
        portfolio_id=portfolio_id,
        date=date,
        value_pln=value_pln,
        composition_change=composition_change,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=[PortfolioValuation.portfolio_id, PortfolioValuation.date],
        set_={
            "value_pln": stmt.excluded.value_pln,
            "composition_change": stmt.excluded.composition_change,
        },
    )
    await db.execute(stmt)
    await db.commit()
