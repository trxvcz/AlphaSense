"""Testy `analytics.benchmark` (plan krok 42, etap 8).

Czysta matematyka na znanych liczbach, bez bazy. Sedno kroku 42 to dwie
rzeczy, których nie widać z samego wykresu, a które psują porównanie po
cichu: **wyrównanie** dwóch różnych kalendarzy (snapshoty portfela vs sesje
giełdy) i **wspólny punkt normalizacji** (pierwszy dzień okna portfela,
nie pierwszy dzień notowań benchmarku).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.modules.analytics.benchmark import Quote, as_of_values, benchmark_index


def _d(day: int) -> date:
    return date(2026, 1, day)


def _quotes(*rows: tuple[int, str]) -> list[Quote]:
    return [Quote(date=_d(day), value=Decimal(value)) for day, value in rows]


def _dates(*days: int) -> list[date]:
    return [_d(day) for day in days]


# --- wyrównanie kalendarzy -------------------------------------------------


def test_as_of_takes_the_last_quote_not_later_than_the_target() -> None:
    """Reguła `max(date) <= D` z CLAUDE.md #3.5 — ta sama, którą stosuje
    wycena portfela. Poniedziałek bez sesji bierze kurs z piątku."""
    quotes = _quotes((2, "100"), (5, "110"))

    values = as_of_values(quotes, _dates(2, 3, 4, 5, 6))

    assert [None if q is None else q.value for q in values] == [
        Decimal("100"),  # 2 stycznia — notowanie tego dnia
        Decimal("100"),  # 3-4 to weekend, notowanie z 2 stycznia niesie dalej
        Decimal("100"),
        Decimal("110"),
        Decimal("110"),
    ]


def test_as_of_never_reaches_into_the_future() -> None:
    """Przed pierwszym notowaniem jest `None`, nie pierwsze późniejsze —
    podstawienie kursu z przyszłości to zaglądanie w wynik, którego w tym
    dniu nikt nie znał."""
    quotes = _quotes((5, "100"))

    values = as_of_values(quotes, _dates(3, 4, 5))

    assert values[0] is None
    assert values[1] is None
    assert values[2] is not None


def test_as_of_reports_the_date_the_value_came_from() -> None:
    """Bez `as_of` „benchmark stoi w miejscu" wygląda tak samo jak „giełda
    była zamknięta"."""
    values = as_of_values(_quotes((2, "100")), _dates(5))

    assert values[0] is not None
    assert values[0].date == _d(2)


def test_as_of_handles_more_quotes_than_targets() -> None:
    """Notowania gęstsze niż daty portfela (krypto 24/7 vs snapshoty
    w dni robocze) — bierzemy ostatnie przed datą, nie pierwsze po."""
    quotes = _quotes((1, "10"), (2, "20"), (3, "30"), (4, "40"), (5, "50"))

    values = as_of_values(quotes, _dates(3, 5))

    assert [q.value for q in values if q is not None] == [Decimal("30"), Decimal("50")]


# --- normalizacja ----------------------------------------------------------


def test_index_starts_at_100_and_tracks_relative_change() -> None:
    points = benchmark_index(_dates(2, 3, 4), _quotes((2, "200"), (3, "220"), (4, "180")))

    assert [p.index for p in points] == [Decimal("100"), Decimal("110"), Decimal("90")]


def test_index_is_anchored_to_the_portfolio_start_not_the_quote_start() -> None:
    """Benchmark ma notowania dłużej niż portfel ma snapshotów. Bazą jest
    pierwszy dzień OKNA PORTFELA — inaczej obie linie startowałyby w różnych
    punktach osi X i porównanie byłoby fałszywe."""
    quotes = _quotes((1, "50"), (2, "200"), (3, "220"))

    points = benchmark_index(_dates(2, 3), quotes)

    assert points[0].index == Decimal("100"), "baza to 2 stycznia (start portfela), nie 1 stycznia"
    assert points[1].index == Decimal("110")


def test_index_uses_the_carried_quote_as_base_when_window_opens_on_a_holiday() -> None:
    """Okno portfela zaczyna się w dniu bez sesji — bazą jest ostatnie
    notowanie sprzed niego, nie pierwsze po. Bez tego wykres gubiłby
    początek serii dokładnie wtedy, gdy zakres wypada w święto."""
    quotes = _quotes((2, "200"), (6, "240"))

    points = benchmark_index(_dates(5, 6), quotes)

    assert points[0].as_of == _d(2)
    assert points[0].index == Decimal("100")
    assert points[1].index == Decimal("120")


def test_no_quote_at_or_before_the_start_gives_empty_series() -> None:
    """Porównanie jest niemożliwe — linia ma się NIE pojawić, zamiast pojawić
    się przesunięta względem portfela (CLAUDE.md #3.15)."""
    assert benchmark_index(_dates(2, 3), _quotes((5, "100"))) == ()


def test_empty_inputs_give_empty_series() -> None:
    assert benchmark_index([], _quotes((2, "100"))) == ()
    assert benchmark_index(_dates(2), []) == ()


def test_zero_base_gives_empty_series() -> None:
    """Normalizacja dzieliłaby przez zero — brak serii, nie wyjątek."""
    assert benchmark_index(_dates(2, 3), _quotes((2, "0"), (3, "100"))) == ()


# --- przeliczenie na PLN (decyzja 4) --------------------------------------


def test_foreign_benchmark_is_converted_to_pln() -> None:
    """Decyzja 4 planu etapu 8: kurs jest częścią realnego wyniku inwestora.
    Indeks bez zmiany + osłabienie złotego o 10% = benchmark w PLN na +10%."""
    quotes = _quotes((2, "100"), (3, "100"))
    fx = _quotes((2, "4"), (3, "4.4"))

    points = benchmark_index(_dates(2, 3), quotes, fx)

    assert [p.value_pln for p in points] == [Decimal("400"), Decimal("440")]
    assert points[1].index == Decimal("110")


def test_fx_follows_the_same_max_date_rule() -> None:
    """NBP nie publikuje tabel w weekendy — kurs z piątku obowiązuje
    w poniedziałek (CLAUDE.md #3.5)."""
    quotes = _quotes((2, "100"), (5, "110"))
    fx = _quotes((2, "4"))

    points = benchmark_index(_dates(2, 5), quotes, fx)

    assert points[1].value_pln == Decimal("440"), "kurs z 2 stycznia niesie na 5 stycznia"


def test_missing_fx_at_the_start_gives_empty_series() -> None:
    """Notowanie jest, kursu nie ma — nie da się wyrazić benchmarku w PLN,
    więc porównania nie ma. Cichy mnożnik 1 udawałby, że indeks w USD jest
    kwotą w PLN."""
    assert benchmark_index(_dates(2, 3), _quotes((2, "100")), _quotes((5, "4"))) == ()


def test_pln_benchmark_needs_no_fx_at_all() -> None:
    """`ETFBW20TR` jest notowany w PLN — przeliczenie jest tożsamościowe
    i wołający po prostu nie podaje kursów (decyzja 8 planu etapu 8)."""
    points = benchmark_index(_dates(2, 3), _quotes((2, "100"), (3, "110")), None)

    assert [p.value_pln for p in points] == [Decimal("100"), Decimal("110")]
    assert points[1].index == Decimal("110")
