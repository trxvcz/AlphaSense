"""Testy jednostkowe silnika wyceny (`service.value_position`) — wzór skill
`analityka-struktury`: `value_pln(h) = quantity × close_adj × fx_pln`.

Bez bazy, bez mocków ORM (docs/konwencje.md) — `value_position` jest
funkcją czystą (bierze już-pobrane liczby, nie robi I/O); orkiestracja I/O
wokół niej (`service._value_pairs`, kursy NBP/ceny z bazy) jest pokryta
testami integracyjnymi w `tests/integration/test_holdings.py`.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.modules.portfolio.service import value_position

TODAY = date(2026, 7, 27)


def test_value_position_basic_formula() -> None:
    value_pln, stale, as_of, unrealized_pl = value_position(
        quantity=Decimal("10"),
        close_adj=Decimal("100"),
        price_date=TODAY,
        fx_pln=Decimal("4"),
        on_date=TODAY,
    )
    assert value_pln == Decimal("4000")
    assert stale is False
    assert as_of == TODAY
    assert unrealized_pl is None


def test_value_position_pln_fx_is_one() -> None:
    """Dla PLN wołający (`service._value_pairs`) przekazuje `fx_pln=1` bez
    pytania NBP — ten test weryfikuje samą matematykę tego przypadku."""
    value_pln, _stale, _as_of, _pl = value_position(
        quantity=Decimal("3"),
        close_adj=Decimal("50"),
        price_date=TODAY,
        fx_pln=Decimal("1"),
        on_date=TODAY,
    )
    assert value_pln == Decimal("150")


def test_value_position_missing_price_is_stale_and_excluded() -> None:
    """Brak notowania (żaden `Price` z `date <= D`) → `stale=True`,
    `value_pln=None` (wyłączona z sumy portfela, nigdy zero), `as_of=None`
    (nie znamy nawet daty jakiejkolwiek ceny)."""
    value_pln, stale, as_of, unrealized_pl = value_position(
        quantity=Decimal("5"),
        close_adj=None,
        price_date=None,
        fx_pln=None,
        on_date=TODAY,
    )
    assert value_pln is None
    assert stale is True
    assert as_of is None
    assert unrealized_pl is None


def test_value_position_missing_fx_is_stale_and_excluded_but_as_of_known() -> None:
    """Cena jest, kursu NBP brak (waluta ≠ PLN bez notowania) → wyłączona
    z sumy, ale `as_of` = data ceny, która jest znana."""
    price_date = date(2026, 7, 24)
    value_pln, stale, as_of, unrealized_pl = value_position(
        quantity=Decimal("5"),
        close_adj=Decimal("200"),
        price_date=price_date,
        fx_pln=None,
        on_date=TODAY,
    )
    assert value_pln is None
    assert stale is True
    assert as_of == price_date
    assert unrealized_pl is None


def test_value_position_old_price_is_stale_but_still_included_in_sum() -> None:
    """Cena starsza niż `D` (cofnięcie do ostatniego dnia roboczego,
    CLAUDE.md #3.5 — normalny tryb pracy w weekend/święto) nadal jest
    liczona, tylko oznaczona `stale=True` — nie jest wyzerowana."""
    price_date = date(2026, 7, 24)  # piątek; TODAY to poniedziałek
    value_pln, stale, as_of, _pl = value_position(
        quantity=Decimal("2"),
        close_adj=Decimal("10"),
        price_date=price_date,
        fx_pln=Decimal("1"),
        on_date=TODAY,
    )
    assert value_pln == Decimal("20")
    assert stale is True
    assert as_of == price_date


def test_value_position_unrealized_pl_with_avg_cost() -> None:
    """`pl(h) = (cena_bieżąca_pln - avg_cost_pln) × quantity`."""
    value_pln, _stale, _as_of, unrealized_pl = value_position(
        quantity=Decimal("10"),
        close_adj=Decimal("100"),
        price_date=TODAY,
        fx_pln=Decimal("4"),
        on_date=TODAY,
        avg_cost=Decimal("300"),
        avg_cost_fx_pln=Decimal("4"),
    )
    # cena PLN/jednostkę = 100 × 4 = 400; koszt PLN/jednostkę = 300 × 4 = 1200
    assert value_pln == Decimal("4000")
    assert unrealized_pl == Decimal("-8000")


def test_value_position_quantizes_to_eight_decimal_places() -> None:
    """`value_pln`/`unrealized_pl` są zaokrąglane do precyzji `NUMERIC(20,8)`
    (`ROUND_HALF_UP`) zanim wyjdą z `value_position` — bez tego mnożenie
    trzech liczb 8-miejscowych (`quantity × close_adj × fx_pln`, jak
    faktycznie przechowywane w bazie) daje >20 miejsc po przecinku
    (code-review etapu 5, znalezione żywym testem: `close_adj`/`fx_pln`
    „ładne" w poprzednich testach tego pliku nigdy nie ujawniały tego
    buga — stąd celowo "brzydkie" liczby tutaj)."""
    value_pln, _stale, _as_of, unrealized_pl = value_position(
        quantity=Decimal("0.03000000"),
        close_adj=Decimal("64144.64280000"),
        price_date=TODAY,
        fx_pln=Decimal("3.80120000"),
        on_date=TODAY,
        avg_cost=Decimal("70000.00000000"),
        avg_cost_fx_pln=Decimal("3.75000000"),
    )
    assert value_pln == Decimal("7314.79848634")
    assert str(value_pln) == "7314.79848634"
    assert unrealized_pl == Decimal("-560.20151366")
    assert str(unrealized_pl) == "-560.20151366"


def test_value_position_without_avg_cost_has_no_unrealized_pl() -> None:
    """Pozycja bez podanego kosztu nabycia nie dostaje P/L — `None`, nigdy
    `0` (skill `analityka-struktury`: „nie sumuj jako zero")."""
    _value_pln, _stale, _as_of, unrealized_pl = value_position(
        quantity=Decimal("10"),
        close_adj=Decimal("100"),
        price_date=TODAY,
        fx_pln=Decimal("4"),
        on_date=TODAY,
    )
    assert unrealized_pl is None
