"""Logika domenowa modułu `portfolio`: CRUD portfeli/pozycji (z bumpem
`holdings_version`/`holdings_changed_at` przy każdej mutacji `holdings`),
silnik wyceny PLN, `summary`, seria `valuations` (plan kroki 25-28, etap 5).

Wzór wyceny (skill `analityka-struktury`, NIE odstępuj):

    value_pln(h) = quantity(h) × close_adj(asset, D) × fx_pln(currency(asset), D)

Pozycja bez ceny (żaden `Price` z `date <= D`) albo bez kursu NBP (waluta
≠ PLN) nie jest liczona jako zero — wyłączona z sumy portfela, oznaczona
`stale=True`. Cena starsza niż `D` (weekend/święto — `max(date) <= D`) jest
nadal liczona (nie wyzerowana), tylko oznaczona `stale=True` z `as_of` =
data tej ceny — to rozróżnienie żyje w `value_position` (funkcja czysta,
bez I/O, testowana w `tests/unit/test_valuation.py`).

`routes.py` woła wyłącznie funkcje stąd — zero SQL w routingu (skill
`fastapi-modul`). Wyjątki domenowe z `core/errors.py`, nigdy
`HTTPException`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_UP, Decimal
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import ConflictError, ValidationError
from app.modules.marketdata import repository as marketdata_repository
from app.modules.marketdata.models import Asset
from app.modules.portfolio import repository
from app.modules.portfolio.models import Holding, Portfolio, PortfolioValuation


def today() -> date:
    """„Dzisiaj" dla wyceny live — `datetime.now(UTC).date()` (konwencja
    repo, patrz `marketdata/service.py:_is_fresh`), nigdy `date.today()`
    (zależne od strefy czasowej serwera)."""
    return datetime.now(UTC).date()


_MONEY_QUANT = Decimal("0.00000001")  # 8 miejsc — precyzja NUMERIC(20,8)
_PCT_QUANT = Decimal("0.0001")  # 4 miejsca — pct to ułamek, nie kwota PLN


def _quantize_money(value: Decimal) -> Decimal:
    """Zaokrągla kwotę PLN do precyzji `NUMERIC(20,8)` (`ROUND_HALF_UP`,
    skill `fastapi-modul`: „backend liczy z pełną precyzją i zaokrągla
    wyłącznie na końcu, jawnie, przez quantize"). Bez tego mnożenie
    `quantity × close_adj × fx_pln` (każdy operand już 8 miejsc) potrafi
    dać >20 miejsc po przecinku w wyniku Decimal — poprawne matematycznie,
    ale niezgodne z kontraktem API (`docs/api-kontrakt.md` pokazuje
    zawsze 8 miejsc) i brzydkie dla frontendu (code-review etapu 5,
    znalezione żywym testem: `"7697.356800000000000000000000"` zamiast
    `"7697.35680000"`)."""
    return value.quantize(_MONEY_QUANT, rounding=ROUND_HALF_UP)


def _quantize_pct(value: Decimal) -> Decimal:
    """Zaokrągla ułamek (`ChangeOut.pct`) do 4 miejsc — nie jest kwotą PLN
    o stałej skali 8 miejsc, ale wynik dzielenia (`delta / previous`) wciąż
    potrzebuje jawnego cięcia precyzji z tego samego powodu co
    `_quantize_money` (kontekst Decimal ma domyślnie 28 cyfr znaczących)."""
    return value.quantize(_PCT_QUANT, rounding=ROUND_HALF_UP)


class _Unset:
    """Sentinel PATCH: pole pominięte w żądaniu. `quantity` nigdy nie jest
    legalnie `None` (kolumna `NOT NULL`), więc dla niego wystarcza unia z
    samym sentinelem; `avg_cost`/`cost_currency`/`note` SĄ nullable, więc
    dla nich jawny `None` ma osobne, sensowne znaczenie („wyczyść") —
    stąd `T | None | _Unset` dla tej trójki."""

    __slots__ = ()

    def __repr__(self) -> str:
        return "UNSET"


UNSET = _Unset()


@dataclass(frozen=True, slots=True)
class HoldingUpdate:
    """Częściowa aktualizacja pozycji — `UNSET` = pole pominięte w PATCH."""

    quantity: Decimal | _Unset = UNSET
    avg_cost: Decimal | None | _Unset = UNSET
    cost_currency: str | None | _Unset = UNSET
    note: str | None | _Unset = UNSET


@dataclass(frozen=True, slots=True)
class ValuedHolding:
    """Jedna pozycja po wycenie na dany dzień."""

    holding: Holding
    asset: Asset
    value_pln: Decimal | None
    stale: bool
    as_of: date | None
    unrealized_pl: Decimal | None
    split_suspected: bool


@dataclass(frozen=True, slots=True)
class PortfolioValue:
    """Wynik wyceny całego portfela na `as_of` — `total_pln` pomija
    pozycje bez ceny/kursu (`value_pln is None`), zgodnie z zasadą „nie
    licz jako zero"."""

    total_pln: Decimal
    as_of: date
    holdings: list[ValuedHolding]
    stale_count: int


@dataclass(frozen=True, slots=True)
class Change:
    abs: Decimal
    pct: Decimal


@dataclass(frozen=True, slots=True)
class Summary:
    value_pln: Decimal
    change_1d: Change | None
    change_ytd: Change | None
    as_of: date
    stale_assets: int


def value_position(
    *,
    quantity: Decimal,
    close_adj: Decimal | None,
    price_date: date | None,
    fx_pln: Decimal | None,
    on_date: date,
    avg_cost: Decimal | None = None,
    avg_cost_fx_pln: Decimal | None = None,
) -> tuple[Decimal | None, bool, date | None, Decimal | None]:
    """Silnik wyceny jednej pozycji na już-pobrane liczby (bez I/O) — jądro
    czyste i testowane bez bazy (`tests/unit/test_valuation.py`).

    `close_adj`/`price_date`/`fx_pln` — `None` sygnalizuje brak notowania
    (żaden `Price` z `date <= on_date`) albo brak kursu NBP (dla `close_adj`
    nieznanego, `fx_pln` nigdy nie jest w ogóle sprawdzany przez wołającego).
    Dla aktywów w PLN wołający przekazuje `fx_pln=Decimal("1")` — ta funkcja
    nie zna pojęcia waluty, tylko liczby (decyzja: przeliczenie „czy pytać
    NBP o PLN" należy do orkiestracji I/O w `_value_pairs`, nie do wzoru).

    Zwraca `(value_pln, stale, as_of, unrealized_pl)`:
    - brak `close_adj` → `(None, True, None, None)` — nie ma nawet daty.
    - `close_adj` jest, brak `fx_pln` → `(None, True, price_date, None)` —
      znamy datę ceny, nie umiemy przeliczyć na PLN.
    - oba są → wyceniona zawsze (nawet gdy `price_date < on_date`, czyli
      cena sprzed weekendu/święta — CLAUDE.md #3.5 „cofanie do ostatniego
      dnia roboczego" to normalny tryb pracy, nie błąd), `stale` tylko
      informuje UI, że to nie dzisiejsza cena.
    - `unrealized_pl` liczony tylko, gdy oba `avg_cost`/`avg_cost_fx_pln`
      podane (pozycja bez kosztu zostaje bez P/L, nigdy `0`).
    """
    if close_adj is None:
        return None, True, None, None
    if fx_pln is None:
        return None, True, price_date, None

    price_per_unit_pln = close_adj * fx_pln
    value_pln = _quantize_money(quantity * price_per_unit_pln)
    stale = price_date is not None and price_date < on_date

    unrealized_pl: Decimal | None = None
    if avg_cost is not None and avg_cost_fx_pln is not None:
        avg_cost_pln = avg_cost * avg_cost_fx_pln
        unrealized_pl = _quantize_money((price_per_unit_pln - avg_cost_pln) * quantity)

    return value_pln, stale, price_date, unrealized_pl


async def _value_pairs(
    db: AsyncSession, pairs: list[tuple[Holding, Asset]], on_date: date
) -> list[ValuedHolding]:
    """Orkiestracja I/O wokół `value_position`: pobiera cenę/kursy/
    heurystykę splitu per pozycja i składa `ValuedHolding`.

    Kursy NBP cache'owane per wywołanie (jedna pozycja w słowniku na
    walutę) — kilka pozycji USD w tym samym portfelu odpytuje `fx_rates`
    o dany dzień raz, nie N razy. `"PLN"` jest w cache z góry jako `1` —
    nigdy nie odpytujemy NBP o złotówkę (CLAUDE.md, skill
    `analityka-struktury`: „Dla aktywów w PLN fx_pln = 1").
    """
    settings = get_settings()
    fx_cache: dict[str, Decimal | None] = {"PLN": Decimal("1")}

    async def rate(currency: str) -> Decimal | None:
        if currency not in fx_cache:
            fx_cache[currency] = await marketdata_repository.get_rate_pln(db, currency, on_date)
        return fx_cache[currency]

    result: list[ValuedHolding] = []
    for holding, asset in pairs:
        split_suspected = await marketdata_repository.detect_price_jump(
            db, asset.id, on_date, threshold=settings.split_detection_threshold
        )
        price = await marketdata_repository.get_latest_price(db, asset.id, on_date)
        close_adj = price.close_adj if price is not None else None
        price_date = price.date if price is not None else None

        fx_pln: Decimal | None = None
        if close_adj is not None:
            fx_pln = await rate(asset.currency)

        avg_cost_fx: Decimal | None = None
        if (
            holding.avg_cost is not None
            and holding.cost_currency is not None
            and close_adj is not None
            and fx_pln is not None
        ):
            avg_cost_fx = await rate(holding.cost_currency)

        value_pln, stale, as_of, unrealized_pl = value_position(
            quantity=holding.quantity,
            close_adj=close_adj,
            price_date=price_date,
            fx_pln=fx_pln,
            on_date=on_date,
            avg_cost=holding.avg_cost,
            avg_cost_fx_pln=avg_cost_fx,
        )
        result.append(
            ValuedHolding(
                holding=holding,
                asset=asset,
                value_pln=value_pln,
                stale=stale,
                as_of=as_of,
                unrealized_pl=unrealized_pl,
                split_suspected=split_suspected,
            )
        )
    return result


async def current_value(db: AsyncSession, portfolio: Portfolio, on_date: date) -> PortfolioValue:
    """Wycena całego portfela na `on_date` — silnik wołany też przez
    worker snapshotów EOD (skill `job-eod`, poza zakresem tego modułu)."""
    pairs = await repository.list_holdings_with_assets(db, portfolio.id)
    valued = await _value_pairs(db, pairs, on_date)

    total = Decimal("0")
    stale_count = 0
    for vh in valued:
        if vh.value_pln is not None:
            total += vh.value_pln
        if vh.stale:
            stale_count += 1

    return PortfolioValue(total_pln=total, as_of=on_date, holdings=valued, stale_count=stale_count)


async def list_valued_holdings(db: AsyncSession, portfolio: Portfolio) -> list[ValuedHolding]:
    """`GET /portfolios/{id}/holdings` — pozycje wycenione na „dziś"."""
    value = await current_value(db, portfolio, today())
    return value.holdings


async def list_holding_asset_ids(db: AsyncSession, portfolio: Portfolio) -> list[UUID]:
    """`asset_id` wszystkich pozycji portfela, bez wyceny — używane przez
    `analytics.service._eod_marker` (plan krok 31, CLAUDE.md #3.7) do
    zbudowania klucza cache **przed** ewentualnym pełnym `current_value`
    (który per pozycja dociąga cenę/kurs/heurystykę splitu — właśnie to
    kosztowne wywołanie ma omijać trafienie w cache). Reużywa ten sam
    tani `JOIN` co `current_value` (`repository.list_holdings_with_assets`);
    na trafienie w cache ta funkcja jest jedynym zapytaniem do bazy, na
    pudło wykonuje się drugi raz wewnątrz `current_value` — świadomie
    zaakceptowany, tani koszt podwójnego odczytu tej samej, małej tabeli
    `holdings`, w zamian za brak refaktoru `current_value` do przyjmowania
    już pobranych par."""
    pairs = await repository.list_holdings_with_assets(db, portfolio.id)
    return [holding.asset_id for holding, _ in pairs]


def _change(current: Decimal, previous: Decimal | None) -> Change | None:
    """`None`, gdy nie ma z czym porównać (brak historii — normalne,
    zanim worker zrobi pierwszy snapshot) albo poprzednia wartość to `0`
    (dzielenie przez zero — brak procentowej zmiany nie jest błędem)."""
    if previous is None or previous == 0:
        return None
    delta = current - previous
    return Change(abs=_quantize_money(delta), pct=_quantize_pct(delta / previous))


async def get_summary(db: AsyncSession, portfolio: Portfolio) -> Summary:
    """`GET /portfolios/{id}/summary` — wartość live + zmiana d/d i YTD
    czytane z `portfolio_valuations` (mogą być `None`, jeśli worker jeszcze
    nie zrobił snapshotu, krok 27 poza zakresem tego modułu)."""
    d = today()
    value = await current_value(db, portfolio, d)
    previous = await repository.get_previous_valuation(db, portfolio.id, before=d)
    year_start = date(d.year, 1, 1)
    first_of_year = await repository.get_first_valuation_since(db, portfolio.id, since=year_start)

    return Summary(
        value_pln=value.total_pln,
        change_1d=_change(value.total_pln, previous.value_pln if previous is not None else None),
        change_ytd=_change(
            value.total_pln, first_of_year.value_pln if first_of_year is not None else None
        ),
        as_of=d,
        stale_assets=value.stale_count,
    )


async def list_valuations(
    db: AsyncSession, portfolio: Portfolio, *, range_: str
) -> list[PortfolioValuation]:
    """`GET /portfolios/{id}/valuations?range=` — seria rosnąco po dacie."""
    return await repository.list_valuations(db, portfolio.id, range_=range_, today=today())


async def list_portfolios(db: AsyncSession, *, user_id: UUID) -> list[Portfolio]:
    return await repository.list_portfolios(db, user_id=user_id)


async def create_portfolio(db: AsyncSession, *, user_id: UUID, name: str, type_: str) -> Portfolio:
    return await repository.create_portfolio(db, user_id=user_id, name=name, type_=type_)


async def update_portfolio(
    db: AsyncSession, portfolio: Portfolio, *, name: str | None, type_: str | None
) -> Portfolio:
    return await repository.update_portfolio(db, portfolio, name=name, type_=type_)


async def delete_portfolio(db: AsyncSession, portfolio: Portfolio) -> None:
    await repository.delete_portfolio(db, portfolio)


async def _require_portfolio(db: AsyncSession, portfolio_id: UUID) -> Portfolio:
    """Odnajduje portfel nadrzędny pozycji już zweryfikowanej przez
    `get_owned_holding` (`Holding.portfolio_id`). `None` tu oznaczałoby
    złamany FK — asercja obronna, nie ścieżka biznesowa (ten sam wzorzec co
    `_link_market_index` w `app/db/seed.py`)."""
    portfolio = await repository.get_portfolio_by_id(db, portfolio_id)
    if portfolio is None:
        raise RuntimeError(f"Holding wskazuje na nieistniejący portfolio_id={portfolio_id}")
    return portfolio


async def create_holding(
    db: AsyncSession,
    portfolio: Portfolio,
    *,
    asset_id: UUID,
    quantity: Decimal,
    avg_cost: Decimal | None,
    cost_currency: str | None,
    note: str | None,
) -> ValuedHolding:
    """Dodaje pozycję i zwraca jej wycenę na „dziś".

    `ValidationError` (422), jeśli `asset_id` nie odnosi się do istniejącego
    aktywa. `ConflictError` (409), jeśli pozycja dla tego aktywa już istnieje
    w portfelu — wykryte przez `IntegrityError` z `UNIQUE(portfolio_id,
    asset_id)` przy `commit()` (baza jest jedynym źródłem prawdy o
    duplikacie, nie dodatkowy `SELECT` przed insertem — unika TOCTOU).
    """
    asset = await repository.get_asset(db, asset_id)
    if asset is None:
        raise ValidationError("Nieznane aktywo")

    cost_currency_norm = cost_currency.upper() if cost_currency else None
    try:
        holding = await repository.create_holding(
            db,
            portfolio,
            asset_id=asset_id,
            quantity=quantity,
            avg_cost=avg_cost,
            cost_currency=cost_currency_norm,
            note=note,
            changed_at=today(),
        )
    except IntegrityError as exc:
        await db.rollback()
        raise ConflictError("Pozycja dla tego aktywa już istnieje w portfelu") from exc

    valued = await _value_pairs(db, [(holding, asset)], today())
    return valued[0]


async def update_holding(
    db: AsyncSession, holding: Holding, update: HoldingUpdate
) -> ValuedHolding:
    """Aktualizuje pola obecne w `update` (patrz `HoldingUpdate`/`UNSET`).

    `ValidationError` (422), jeśli stan **po scaleniu** narusza
    `avg_cost wymaga cost_currency` (CHECK `avg_cost_needs_currency`
    w bazie) — sprawdzane tu, na finalnym stanie, nie na samym żądaniu
    PATCH, bo PATCH może dotykać tylko jednego z tej pary pól.

    `PATCH {}` (żadne pole obecne w `update`) NIE bumpuje `holdings_version`/
    `holdings_changed_at` — code-review etapu 5: bez tego guardu każdy no-op
    PATCH fałszywie oznaczał dzień jako „zmiana składu" dla joba snapshotów
    (`worker/jobs/snapshot_portfolios.py`), co wg ADR-101/skill
    `analityka-struktury` wyłącza ten dzień z serii zwrotów mimo że skład
    faktycznie się nie zmienił.
    """
    changed = False
    if not isinstance(update.quantity, _Unset):
        holding.quantity = update.quantity
        changed = True
    if not isinstance(update.avg_cost, _Unset):
        holding.avg_cost = update.avg_cost
        changed = True
    if not isinstance(update.cost_currency, _Unset):
        holding.cost_currency = update.cost_currency.upper() if update.cost_currency else None
        changed = True
    if not isinstance(update.note, _Unset):
        holding.note = update.note
        changed = True

    if holding.avg_cost is not None and holding.cost_currency is None:
        raise ValidationError("avg_cost wymaga podania cost_currency")

    portfolio = await _require_portfolio(db, holding.portfolio_id)
    asset = await repository.get_asset(db, holding.asset_id)
    if asset is None:
        raise RuntimeError(f"Holding {holding.id} wskazuje na nieistniejące asset_id")

    if changed:
        await repository.update_holding_row(db, portfolio, holding, changed_at=today())

    valued = await _value_pairs(db, [(holding, asset)], today())
    return valued[0]


async def delete_holding(db: AsyncSession, holding: Holding) -> None:
    """Twardy `DELETE` (decyzja produktowa — `Holding` nie jest historią)."""
    portfolio = await _require_portfolio(db, holding.portfolio_id)
    await repository.delete_holding(db, portfolio, holding, changed_at=today())
