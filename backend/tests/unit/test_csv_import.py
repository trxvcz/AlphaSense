"""Parser CSV i arytmetyka scalania pozycji (plan krok 48, etap 9).

Bez bazy — `csv_import.parse` i `service.merge_quantity_and_cost` są czyste
(CLAUDE.md §8: „logika obliczeniowa — testy jednostkowe na znanych liczbach,
bez mocków bazy tam, gdzie obliczenie jest czysto matematyczne"). Wartości
średniej ważonej policzone ręcznie w docstringach testów.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.modules.portfolio import csv_import
from app.modules.portfolio.service import merge_quantity_and_cost

# --- parser -----------------------------------------------------------------


def test_parsuje_kanoniczny_format() -> None:
    result = csv_import.parse("CDR;10;120.50\nPKN;5;65")

    assert result.errors == []
    assert [(row.symbol, row.quantity, row.avg_cost) for row in result.rows] == [
        ("CDR", Decimal("10"), Decimal("120.50")),
        ("PKN", Decimal("5"), Decimal("65")),
    ]
    # Numeracja linii idzie od 1 względem PLIKU — użytkownik ma znaleźć wpis
    # w edytorze, a nie na liście wyników.
    assert [row.line for row in result.rows] == [1, 2]


def test_pomija_naglowek_bom_i_puste_linie() -> None:
    """Plik prosto z polskiego Excela: BOM, nagłówek, puste linie na końcu."""
    content = "﻿symbol;ilosc;cena_nabycia\nCDR;10;120,50\n\n\n"
    result = csv_import.parse(content)

    assert result.errors == []
    assert len(result.rows) == 1
    assert result.rows[0].avg_cost == Decimal("120.50")
    assert result.rows[0].line == 2


def test_przecinek_dziesietny_i_separator_tysiecy() -> None:
    """`1 234,56` z arkusza (spacja nierozdzielająca) to 1234.56, nie błąd."""
    result = csv_import.parse("CDR;1 234,56;2 000,00")

    assert result.errors == []
    assert result.rows[0].quantity == Decimal("1234.56")
    assert result.rows[0].avg_cost == Decimal("2000.00")


def test_liczba_z_przecinkiem_i_kropka_jest_bledem() -> None:
    """`1,234.56` (tysiące po angielsku) vs `1.234,56` (po polsku) dają inny
    wynik i nie ma jak rozstrzygnąć — zgadywanie byłoby przybieraniem
    przybliżenia za dane dokładne (CLAUDE.md #3.15)."""
    result = csv_import.parse("CDR;1,234.56;10")

    assert result.rows == []
    assert result.errors[0].message == "Ilość nie jest liczbą"


def test_pusta_cena_nabycia_jest_legalna() -> None:
    """Użytkownik może nie znać ceny nabycia — struktura portfela to nie
    księgowość (CLAUDE.md #1)."""
    result = csv_import.parse("CDR;10;\nPKN;5")

    assert result.errors == []
    assert [row.avg_cost for row in result.rows] == [None, None]


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("CDR;0;10", "Ilość musi być większa od zera"),
        ("CDR;-5;10", "Ilość musi być większa od zera"),
        ("CDR;abc;10", "Ilość nie jest liczbą"),
        ("CDR;10;0", "Cena nabycia musi być większa od zera"),
        ("CDR;10;xyz", "Cena nabycia nie jest liczbą"),
        (";10;5", "Brak symbolu"),
        ("CDR", "Oczekiwano formatu symbol;ilość;cena_nabycia"),
    ],
)
def test_odrzucone_wiersze_maja_powod(line: str, expected: str) -> None:
    # Nagłówek, żeby pierwsza linia nie została uznana za nagłówek i pominięta.
    result = csv_import.parse(f"symbol;ilosc;cena\n{line}")

    assert result.rows == []
    assert [error.message for error in result.errors] == [expected]


def test_jeden_zly_wiersz_nie_przerywa_reszty() -> None:
    result = csv_import.parse("CDR;10;120\nPKN;nie-liczba;5\nPKO;3;40")

    assert [row.symbol for row in result.rows] == ["CDR", "PKO"]
    assert [error.line for error in result.errors] == [2]


def test_powtorzony_symbol_w_pliku_jest_bledem() -> None:
    """Sumowanie po cichu dałoby ilość, której nie ma w żadnej linijce pliku."""
    result = csv_import.parse("CDR;10;120\nCDR;5;130")

    assert [row.symbol for row in result.rows] == ["CDR"]
    assert result.errors[0].line == 2
    assert "powtarza się" in result.errors[0].message


def test_nan_i_infinity_nie_sa_liczbami() -> None:
    """`Decimal` przyjmuje oba literały; żaden nie jest ilością."""
    assert csv_import.parse_number("NaN") is None
    assert csv_import.parse_number("Infinity") is None


def test_zbyt_duzy_plik_przerywa_import() -> None:
    """Rozmiar dotyczy pliku, nie wiersza — nie ma czego raportować per wpis."""
    with pytest.raises(csv_import.CsvTooLargeError):
        csv_import.parse("CDR;1;1\n" * (csv_import.MAX_ROWS + 5))

    with pytest.raises(csv_import.CsvTooLargeError):
        csv_import.parse("x" * (csv_import.MAX_CHARS + 1))


# --- scalanie ---------------------------------------------------------------


def test_srednia_wazona_iloscia() -> None:
    """10 × 100 + 30 × 200 = 7000; 7000 / 40 = 175."""
    quantity, cost = merge_quantity_and_cost(
        old_quantity=Decimal("10"),
        old_cost=Decimal("100"),
        new_quantity=Decimal("30"),
        new_cost=Decimal("200"),
        costs_comparable=True,
    )

    assert quantity == Decimal("40")
    assert cost == Decimal("175.00000000")


def test_srednia_wazona_zaokraglona_do_osmiu_miejsc() -> None:
    """(1 × 10 + 2 × 20) / 3 = 16.666... → 16.66666667 (ROUND_HALF_UP,
    precyzja NUMERIC(20,8))."""
    _, cost = merge_quantity_and_cost(
        old_quantity=Decimal("1"),
        old_cost=Decimal("10"),
        new_quantity=Decimal("2"),
        new_cost=Decimal("20"),
        costs_comparable=True,
    )

    assert cost == Decimal("16.66666667")


@pytest.mark.parametrize(
    ("old_cost", "new_cost", "comparable"),
    [
        (None, Decimal("100"), True),
        (Decimal("100"), None, True),
        (Decimal("100"), Decimal("200"), False),
    ],
)
def test_niepolna_lub_niespojna_cena_daje_none(
    old_cost: Decimal | None, new_cost: Decimal | None, comparable: bool
) -> None:
    """Średnia z liczby znanej i nieznanej nie istnieje, a średnia z kwot w
    dwóch walutach jest liczbą bez znaczenia — w obu wypadkach `None`, nigdy
    wartość „prawdopodobna" (CLAUDE.md #3.15). Ilość scala się mimo to."""
    quantity, cost = merge_quantity_and_cost(
        old_quantity=Decimal("10"),
        old_cost=old_cost,
        new_quantity=Decimal("5"),
        new_cost=new_cost,
        costs_comparable=comparable,
    )

    assert quantity == Decimal("15")
    assert cost is None
