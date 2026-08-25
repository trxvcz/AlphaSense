"""Zapis i odczyt zdarzeń dywidendowych (plan krok 47, etap 9).

Ten sam kształt co `marketdata/repository.py` i `news/repository.py`:
wąskie funkcje przyjmujące `AsyncSession`, bez klasy „repozytorium".

**Zapis przez `ON CONFLICT DO UPDATE`, nie `DO NOTHING`** — inaczej niż
przy newsach. Uzasadnienie w docstringu modelu: zapowiedziana dywidenda
bywa korygowana między deklaracją a wypłatą, więc świeższa odpowiedź
dostawcy jest bliższa prawdzie niż nasza kopia sprzed tygodnia.
"""

from __future__ import annotations

from datetime import date as date_
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import Boolean, literal_column, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.dividends.models import DividendEvent
from app.modules.marketdata.models import Asset, AssetSourceMap
from app.modules.portfolio.models import Holding


async def upsert_dividend_event(
    db: AsyncSession,
    *,
    asset_id: UUID,
    ex_date: date_,
    amount: Decimal,
    currency: str,
    source: str,
    fetched_at: datetime,
    record_date: date_ | None = None,
    pay_date: date_ | None = None,
    declaration_date: date_ | None = None,
) -> bool:
    """Zapisuje zdarzenie. Zwraca `True`, gdy wiersz był nowy.

    Rozróżnienie „nowe" vs „zaktualizowane" jest potrzebne wyłącznie do
    logu przebiegu — `RETURNING` po `DO UPDATE` oddaje jedno i drugie, więc
    nowość poznajemy po `xmax = 0` (Postgres: `xmax` wstawionego wiersza
    jest zerowe, zaktualizowanego — nie). To jedyny sposób, żeby licznik
    w logu mierzył przyrost, a nie rozmiar odpowiedzi dostawcy; ta sama
    pułapka co z licznikiem `upserted` w jobie newsów.
    """
    statement = insert(DividendEvent).values(
        asset_id=asset_id,
        ex_date=ex_date,
        amount=amount,
        currency=currency,
        source=source,
        fetched_at=fetched_at,
        record_date=record_date,
        pay_date=pay_date,
        declaration_date=declaration_date,
    )
    upsert = statement.on_conflict_do_update(
        constraint="uq_dividend_events_asset_ex",
        set_={
            "amount": statement.excluded.amount,
            "currency": statement.excluded.currency,
            "source": statement.excluded.source,
            "fetched_at": statement.excluded.fetched_at,
            "record_date": statement.excluded.record_date,
            "pay_date": statement.excluded.pay_date,
            "declaration_date": statement.excluded.declaration_date,
        },
    )
    # `xmax` jest kolumną systemową Postgresa — nie ma jej w metadanych
    # tabeli, stąd `literal_column` zamiast atrybutu modelu. `.returning()`
    # NA KOŃCU, po `on_conflict_do_update` (ta sama pułapka co w jobie
    # newsów: odwrotna kolejność gubi `excluded`).
    returning = upsert.returning(DividendEvent.id, literal_column("xmax = 0", Boolean))
    result = await db.execute(returning)
    row = result.first()
    return bool(row is not None and row[1])


async def list_portfolio_positions(
    db: AsyncSession, portfolio_id: UUID
) -> list[tuple[UUID, str, str, str, Decimal]]:
    """Pozycje portfela: `(asset_id, symbol, market_code, currency, quantity)`.

    Zapytanie łączy tabele modułów `marketdata` i `portfolio`, ale mieszka
    tutaj, bo jego jedynym konsumentem jest kalendarz dywidend (ta sama
    zasada co `news/repository.list_portfolio_asset_ids`).

    **To nie jest miejsce, w którym dzieje się izolacja danych.**
    `portfolio_id` przychodzi z `get_owned_portfolio` i ta funkcja nigdy
    nie jest wołana z surowym identyfikatorem z żądania (CLAUDE.md #3.2).

    Ilość bierzemy z `holdings`, bo kalendarz szacuje wypłatę dla **tej**
    pozycji. Jedno aktywo bywa w portfelu w kilku wierszach (różne
    `valid_from`, różne noty), więc sumowanie należy do serwisu — tutaj
    zwracamy stan bazy bez interpretacji.
    """
    result = await db.execute(
        select(Asset.id, Asset.symbol, Asset.market_code, Asset.currency, Holding.quantity)
        .join(Holding, Holding.asset_id == Asset.id)
        .where(Holding.portfolio_id == portfolio_id)
        .order_by(Asset.symbol)
    )
    return [(r.id, r.symbol, r.market_code, r.currency, r.quantity) for r in result]


async def list_upcoming_events(
    db: AsyncSession,
    asset_ids: list[UUID],
    *,
    date_from: date_,
    date_to: date_,
) -> list[DividendEvent]:
    """Zdarzenia dla podanych aktywów z ex-datą w przedziale `[from, to]`.

    Sortowanie rosnąco po `ex_date` (a nie malejąco, jak feed newsów): ten
    ekran odpowiada na pytanie „co MNIE czeka najbliżej", więc na górze ma
    być zdarzenie najbliższe, nie najświeżej pobrane.
    """
    if not asset_ids:
        return []
    result = await db.execute(
        select(DividendEvent)
        .where(
            DividendEvent.asset_id.in_(asset_ids),
            DividendEvent.ex_date >= date_from,
            DividendEvent.ex_date <= date_to,
        )
        .order_by(DividendEvent.ex_date, DividendEvent.asset_id)
    )
    return list(result.scalars().all())


async def list_covered_asset_ids(db: AsyncSession, provider: str) -> set[UUID]:
    """Aktywa mające mapowanie na dostawcę dywidend.

    **Pokrycie rozstrzyga mapowanie, nie obecność zdarzeń w bazie.**
    Aktywo bez mapowania (dziś: cała GPW) i spółka, która po prostu nie
    płaci dywidendy, mają w tabeli `dividend_events` identycznie zero
    wierszy — a to dwie zupełnie różne informacje dla użytkownika
    (CLAUDE.md #3.15).
    """
    result = await db.execute(
        select(AssetSourceMap.asset_id).where(AssetSourceMap.provider == provider).distinct()
    )
    return set(result.scalars().all())


async def list_provider_symbols(db: AsyncSession, provider: str) -> list[tuple[UUID, str, str]]:
    """Aktywa **trzymane przez kogokolwiek** i mapowane na dostawcę:
    `(asset_id, provider_symbol, currency)`.

    Zawężenie do aktywów realnie posiadanych jest tu wymogiem budżetowym,
    nie optymalizacją: darmowy plan Alpha Vantage to 25 zapytań na dobę,
    dzielone z jobem sentymentu. Pytanie o aktywo, którego nikt nie ma,
    kosztuje tyle samo co pytanie o pozycję użytkownika, a jego wynik nie
    trafi na żaden ekran.

    Waluta pochodzi z `assets.currency`, bo dostawca jej nie podaje
    (patrz `_parse_entry` w `alphavantage_dividends.py`).
    """
    result = await db.execute(
        select(AssetSourceMap.asset_id, AssetSourceMap.provider_symbol, Asset.currency)
        .join(Asset, Asset.id == AssetSourceMap.asset_id)
        .join(Holding, Holding.asset_id == Asset.id)
        .where(AssetSourceMap.provider == provider, Asset.is_active.is_(True))
        .distinct()
        .order_by(AssetSourceMap.provider_symbol)
    )
    return [(r.asset_id, r.provider_symbol, r.currency) for r in result]
