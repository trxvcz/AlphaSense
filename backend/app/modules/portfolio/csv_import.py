"""Parser kanonicznego CSV z listą pozycji (plan krok 48, etap 9).

Format uzgodniony w planie: `symbol;ilość;cena_nabycia`, separator średnik.
Moduł jest **czysto obliczeniowy** — żadnego I/O, żadnej bazy, żadnej wiedzy
o portfelu. Dzięki temu cała logika tolerancji na realne pliki (Excel, BOM,
przecinek dziesiętny) testuje się bez bazy, a `service.py` dostaje gotową
listę wierszy i zajmuje się wyłącznie mapowaniem symboli na aktywa.

**Dlaczego tolerancja formatu, a nie sztywny `csv.reader`:** plik powstaje
w polskim Excelu albo w Arkuszach Google, więc realnie przychodzi z BOM-em,
przecinkiem dziesiętnym i spacją jako separatorem tysięcy. Odrzucanie takiego
pliku jako „niepoprawny CSV" przerzuca na użytkownika pracę, którą parser
wykonuje w kilku linijkach.

**Czego świadomie nie zgadujemy:** liczby zawierającej jednocześnie przecinek
i kropkę (`1,234.56` to angielskie tysiące, `1.234,56` polskie — obie
konwencje dają inny wynik i nie ma jak rozstrzygnąć, która to). Taki wiersz
jest błędem, a nie wartością „prawdopodobną" (CLAUDE.md #3.15: nie
przedstawiaj przybliżenia jako danych dokładnych).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

# Limity wejścia. Import to jedno żądanie HTTP, które w pesymistycznym
# przypadku wykonuje `MAX_ROWS` zapytań o aktywo — limit jest tu obroną przed
# zapchaniem puli połączeń, nie kosmetyką. 500 pozycji to i tak o rząd
# wielkości więcej niż realny portfel detaliczny.
MAX_ROWS = 500
MAX_CHARS = 100_000

SEPARATOR = ";"

# Separatory tysięcy spotykane w plikach z arkuszy: zwykła spacja, spacja
# nierozdzielająca (U+00A0, wstawia ją Excel) i wąska spacja (U+202F).
_THOUSANDS = (" ", "\u00a0", "\u202f")


@dataclass(frozen=True, slots=True)
class ParsedRow:
    """Poprawny wiersz. `avg_cost is None` = kolumna pusta (użytkownik nie
    zna ceny nabycia) — to legalny import, nie brak danych do uzupełnienia."""

    line: int
    symbol: str
    quantity: Decimal
    avg_cost: Decimal | None


@dataclass(frozen=True, slots=True)
class RowError:
    """Wiersz odrzucony wraz z powodem. `symbol` bywa pusty (wiersz bez pól)
    — służy do pokazania użytkownikowi, o który wpis chodzi, więc nie jest
    identyfikatorem i nie musi być poprawny."""

    line: int
    symbol: str
    message: str


@dataclass(frozen=True, slots=True)
class ParseResult:
    rows: list[ParsedRow]
    errors: list[RowError]


class CsvTooLargeError(ValueError):
    """Wejście przekracza `MAX_CHARS`/`MAX_ROWS` — w przeciwieństwie do błędu
    pojedynczego wiersza przerywa cały import, bo dotyczy pliku, nie wpisu."""


def parse_number(raw: str) -> Decimal | None:
    """Parsuje liczbę z komórki arkusza. `None`, gdy wartość jest pusta albo
    nie da się jej odczytać jednoznacznie.

    Nigdy nie przechodzi przez `float` (CLAUDE.md #3.1) — `Decimal` bierze
    string wprost, po normalizacji separatorów.
    """
    text = raw.strip()
    for space in _THOUSANDS:
        text = text.replace(space, "")
    if not text:
        return None
    if "," in text and "." in text:
        # Niejednoznaczne: patrz docstring modułu.
        return None
    text = text.replace(",", ".")
    try:
        value = Decimal(text)
    except InvalidOperation:
        return None
    # `Decimal` przyjmuje "NaN" i "Infinity" jako poprawne literały; żadna z
    # tych wartości nie jest ilością ani ceną i obie potrafią zatruć wycenę.
    return value if value.is_finite() else None


def parse(content: str) -> ParseResult:
    """Rozbiera zawartość pliku na wiersze poprawne i odrzucone.

    Jeden zły wiersz **nie przerywa importu** — użytkownik dostaje resztę
    pozycji i listę tego, co się nie udało, zamiast komunikatu „popraw plik"
    bez wskazania miejsca. Numer linii jest liczony od 1 względem pliku (a nie
    od pozycji na liście), żeby dało się go znaleźć w edytorze.
    """
    if len(content) > MAX_CHARS:
        raise CsvTooLargeError(f"Plik przekracza {MAX_CHARS} znaków")

    rows: list[ParsedRow] = []
    errors: list[RowError] = []
    seen: dict[str, int] = {}

    for number, raw_line in enumerate(content.lstrip("\ufeff").splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        if number == 1 and _is_header(line):
            continue
        if len(rows) + len(errors) >= MAX_ROWS:
            raise CsvTooLargeError(f"Plik przekracza {MAX_ROWS} wierszy")

        parsed = _parse_line(number, line)
        if isinstance(parsed, RowError):
            errors.append(parsed)
            continue

        key = parsed.symbol.upper()
        first = seen.get(key)
        if first is not None:
            # Dwa wiersze o tym samym symbolu w jednym pliku to prawie zawsze
            # pomyłka przy sklejaniu arkuszy. Sumowanie ich po cichu dałoby
            # ilość, której nie ma w żadnej linijce pliku.
            errors.append(
                RowError(
                    line=parsed.line,
                    symbol=parsed.symbol,
                    message=f"Symbol powtarza się w pliku (pierwszy raz w linii {first})",
                )
            )
            continue
        seen[key] = parsed.line
        rows.append(parsed)

    return ParseResult(rows=rows, errors=errors)


def _is_header(line: str) -> bool:
    """Nagłówek jest opcjonalny i rozpoznawany po treści, nie po deklaracji.

    Warunek jest celowo ostrzejszy niż „kolumna ilości nie jest liczbą":
    wiersz uchodzi za nagłówek dopiero wtedy, gdy **żadne** pole nie jest
    liczbą. Inaczej jednowierszowy plik z literówką w ilości (`CDR;1,234.56;10`)
    zostaje uznany za nagłówek i import kończy się raportem „0 pozycji,
    0 błędów" — czyli milczy dokładnie tam, gdzie ma powiedzieć, co poprawić
    (złapane testem `test_liczba_z_przecinkiem_i_kropka_jest_bledem`).
    """
    fields = line.split(SEPARATOR)
    if len(fields) < 2:
        return False
    return all(parse_number(field) is None for field in fields)


def _parse_line(number: int, line: str) -> ParsedRow | RowError:
    fields = [field.strip() for field in line.split(SEPARATOR)]
    symbol = fields[0] if fields else ""

    if len(fields) < 2:
        return RowError(
            line=number,
            symbol=symbol,
            message="Oczekiwano formatu symbol;ilość;cena_nabycia",
        )
    if not symbol:
        return RowError(line=number, symbol="", message="Brak symbolu")

    quantity = parse_number(fields[1])
    if quantity is None:
        return RowError(line=number, symbol=symbol, message="Ilość nie jest liczbą")
    if quantity <= 0:
        # Zero nie jest błędem bazy (CHECK dopuszcza `quantity >= 0`), ale w
        # imporcie jest bezużyteczne: dodawałoby pozycję bez zawartości albo,
        # przy scalaniu, nie zmieniało niczego.
        return RowError(line=number, symbol=symbol, message="Ilość musi być większa od zera")

    avg_cost: Decimal | None = None
    if len(fields) > 2 and fields[2]:
        avg_cost = parse_number(fields[2])
        if avg_cost is None:
            return RowError(line=number, symbol=symbol, message="Cena nabycia nie jest liczbą")
        if avg_cost <= 0:
            return RowError(
                line=number, symbol=symbol, message="Cena nabycia musi być większa od zera"
            )

    return ParsedRow(line=number, symbol=symbol, quantity=quantity, avg_cost=avg_cost)
