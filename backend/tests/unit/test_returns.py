"""Testy `analytics.returns` (plan krok 40, etap 8).

Czysta matematyka na znanych liczbach — bez bazy i bez mocków (CLAUDE.md §8).
Sedno kroku 40 i najczęstsze źródło błędów: dzień `composition_change=true`
**zrywa ogniwo**, a nie kasuje obu dni. Test na to jest obowiązkowy (skill
`analityka-struktury`, sekcja „Zwroty").
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.modules.analytics.returns import (
    ValuationPoint,
    chain_index,
    chain_link,
    daily_returns,
    period_return,
)


def _points(*rows: tuple[int, str] | tuple[int, str, bool]) -> list[ValuationPoint]:
    """`(dzień stycznia 2026, wartość [, composition_change])` → punkty."""
    return [
        ValuationPoint(
            date=date(2026, 1, row[0]),
            value_pln=Decimal(row[1]),
            composition_change=bool(row[2]) if len(row) > 2 else False,
        )
        for row in rows
    ]


# --- seria zwrotów ---------------------------------------------------------


def test_known_series_gives_known_returns() -> None:
    """`[100, 110, 99]` → `[+10%, -10%]` (przykład ze skilla)."""
    series = daily_returns(_points((5, "100"), (6, "110"), (7, "99")))

    assert [r.ret for r in series.returns] == [Decimal("0.1"), Decimal("-0.1")]
    assert series.links == 2
    assert series.skipped == 0


def test_link_carries_both_ends_of_the_gap() -> None:
    """Ogniwo niesie datę początku i końca — bez tego zwrot za weekend
    (piątek → poniedziałek) jest na wykresie nieodróżnialny od dziennego."""
    series = daily_returns(_points((2, "100"), (5, "110")))

    (link,) = series.returns
    assert link.previous_date == date(2026, 1, 2)
    assert link.date == date(2026, 1, 5)
    assert link.value_pln == Decimal("110")


def test_gap_in_series_joins_the_chain_instead_of_breaking_it() -> None:
    """Decyzja 6 planu: przerwa (weekend, brak przebiegu workera) łączy.

    Zrywanie przy każdej dziurze wycinałoby przy nieregularnym workerze
    większość okresu i zaniżało zwrot bez ostrzeżenia.
    """
    series = daily_returns(_points((2, "100"), (20, "110")))

    assert series.links == 1
    assert series.skipped == 0
    assert series.returns[0].ret == Decimal("0.1")


# --- zmiana składu: sedno kroku 40 ----------------------------------------


def test_composition_change_day_has_no_return() -> None:
    """Portfel 1000 PLN → dopisana pozycja warta 500 → snapshot 1500.

    Zwrot za ten dzień NIE ISTNIEJE (nie +50%) — przykład wprost ze skilla
    `analityka-struktury`.
    """
    series = daily_returns(_points((5, "1000"), (6, "1500", True)))

    assert series.returns == ()
    assert series.skipped_composition_change == 1


def test_composition_change_breaks_one_link_not_both_days() -> None:
    """Po dopisaniu pozycji portfel żyje dalej normalnie — zwrot NASTĘPNEGO
    dnia musi zostać w serii.

    Skasowanie obu dni (częsty odruch) wycięłoby prawdziwe +10% z 1500 na
    1650 i zaniżyło zwrot za okres.
    """
    series = daily_returns(_points((5, "1000"), (6, "1500", True), (7, "1650")))

    (link,) = series.returns
    assert link.date == date(2026, 1, 7)
    assert link.previous_date == date(2026, 1, 6), "bazą jest dzień zmiany składu, nie sprzed niej"
    assert link.ret == Decimal("0.1")
    assert series.skipped_composition_change == 1


def test_period_return_ignores_the_deposit_entirely() -> None:
    """Ten sam portfel co wyżej: 1000 → 1100 (+10%), dopłata do 1600,
    potem 1760 (+10%). Zwrot za okres to 1,1 × 1,1 - 1 = 21%, mimo że
    wartość urosła z 1000 do 1760 (+76%)."""
    total, series = period_return(_points((5, "1000"), (6, "1100"), (7, "1600", True), (8, "1760")))

    assert total == Decimal("0.21")
    assert series.links == 2
    assert series.skipped_composition_change == 1


def test_first_point_flagged_as_composition_change_is_harmless() -> None:
    """Pierwszy snapshot portfela z definicji ma zmianę składu, ale nie
    zaczyna żadnego ogniwa — nie ma czego zrywać i nie wolno tego liczyć
    jako pominięcie."""
    series = daily_returns(_points((5, "1000", True), (6, "1100")))

    assert series.links == 1
    assert series.skipped == 0


# --- przypadki brzegowe ----------------------------------------------------


def test_empty_and_single_point_series_have_no_returns() -> None:
    """Portfel założony wczoraj nie ma jeszcze zwrotu — to nie jest błąd."""
    assert daily_returns([]).returns == ()
    assert daily_returns(_points((5, "100"))).returns == ()


def test_zero_base_is_skipped_and_counted_separately() -> None:
    """Zwrot z zerowej bazy jest nieokreślony, nie nieskończony — i liczy się
    osobno od zmiany składu, bo znaczy co innego (dane wyglądają źle,
    zamiast: zadziałał ADR-101)."""
    series = daily_returns(_points((5, "0"), (6, "100")))

    assert series.returns == ()
    assert series.skipped_zero_base == 1
    assert series.skipped_composition_change == 0


def test_flat_series_gives_zero_return() -> None:
    total, series = period_return(_points((5, "100"), (6, "100"), (7, "100")))

    assert total == Decimal("0")
    assert [r.ret for r in series.returns] == [Decimal("0"), Decimal("0")]


def test_portfolio_that_lost_everything_gives_minus_one() -> None:
    """Granica dziedziny: -100%, nigdy mniej."""
    total, _ = period_return(_points((5, "100"), (6, "0")))

    assert total == Decimal("-1")


# --- chain_link ------------------------------------------------------------


def test_chain_link_of_empty_series_is_zero() -> None:
    """Element neutralny — sklejanie podokresów, z których jeden jest pusty,
    nie może zmienić wyniku."""
    assert chain_link([]) == Decimal("0")


def test_chain_link_compounds_instead_of_adding() -> None:
    """+10% i -10% to -1%, nie 0% — najczęstszy błąd przy sumowaniu zwrotów."""
    assert chain_link([Decimal("0.1"), Decimal("-0.1")]) == Decimal("-0.01")


def test_chain_link_is_associative_over_subperiods() -> None:
    """Zwrot za rok = złożenie zwrotów kwartalnych. Gdyby ogniwa były
    zaokrąglane przed mnożeniem, ta równość by nie zachodziła."""
    quarterly = [Decimal("0.05"), Decimal("-0.02"), Decimal("0.03"), Decimal("0.01")]

    whole = chain_link(quarterly)
    halves = chain_link([chain_link(quarterly[:2]), chain_link(quarterly[2:])])

    assert whole == halves


# --- indeks łańcuchowy (podstawa wykresu, kroku 41 i 42) -------------------


def test_chain_index_starts_at_base_and_compounds() -> None:
    points = _points((5, "1000"), (6, "1100"), (7, "990"))

    index = chain_index(points)

    assert [p.index for p in index] == [Decimal("100"), Decimal("110"), Decimal("99")]
    assert index[0].ret is None, "pierwszy punkt nie ma poprzednika, więc nie ma zwrotu"


def test_chain_index_stands_still_on_a_broken_link() -> None:
    """Sedno wykresu wyników: wpłata podnosi `value_pln`, ale NIE indeks.

    Gdyby indeks szedł za wartością, wykres pokazywałby dopłatę jako zysk,
    a krok 41 policzyłby z tego wyjście z obsunięcia.
    """
    points = _points((5, "1000"), (6, "1500", True), (7, "1650"))

    index = chain_index(points)

    assert [p.value_pln for p in index] == [Decimal("1000"), Decimal("1500"), Decimal("1650")]
    assert [p.index for p in index] == [Decimal("100"), Decimal("100"), Decimal("110")]
    assert index[1].ret is None, "zwrotu za dzień zmiany składu nie znamy — nie wolno dać zera"
    assert index[2].ret == Decimal("0.1")


def test_chain_index_last_value_agrees_with_period_return() -> None:
    """Indeks i zwrot za okres muszą wychodzić z tych samych ogniw —
    rozjazd oznaczałby dwie różne reguły zrywania w jednym module."""
    points = _points((5, "1000"), (6, "1100"), (7, "1600", True), (8, "1760"))

    total, _ = period_return(points)
    index = chain_index(points)

    assert index[-1].index == Decimal("100") * (Decimal("1") + total)


def test_chain_index_of_empty_series_is_empty() -> None:
    assert chain_index([]) == ()
