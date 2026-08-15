"""Wyrównanie i normalizacja serii benchmarku (plan krok 42, etap 8).

Czysta matematyka na `Decimal` — bez sesji bazy, bez I/O. Wołający
(`analytics.service.performance`) podaje daty snapshotów portfela oraz
pobrane wcześniej serie notowań i kursów, dostaje serię indeksu benchmarku
gotową do narysowania obok portfela.

## Dwa problemy, które ten moduł rozwiązuje

**Wyrównanie.** Snapshoty portfela i notowania benchmarku nie leżą na tych
samych datach. Portfel dostaje snapshot w każdy dzień, w którym przebiegł
worker; benchmark ma notowanie w każdy dzień sesji swojej giełdy. Święto
GPW, święto amerykańskie i weekend rozjeżdżają te dwa kalendarze w obie
strony. Reguła jest ta sama co w całym silniku wyceny (CLAUDE.md #3.5,
`get_latest_price`): dla daty `D` bierzemy **ostatnie notowanie nie
późniejsze niż `D`** — nie interpolujemy i nie przesuwamy dat portfela.

**Normalizacja.** Obie serie startują od 100 w pierwszym dniu okna, więc
wykres odpowiada na pytanie „czy portfel pobił rynek", a nie „ile kosztuje
jednostka indeksu". Punktem odniesienia jest **pierwsza data serii
portfela**, nie pierwsza data notowań benchmarku: gdyby każda seria
normalizowała się do własnego początku, dwie linie startowałyby w różnych
punktach osi X i porównanie byłoby fałszywe.

Konsekwencja: brak notowania benchmarku w dniu startu (lub wcześniej)
oznacza, że **nie da się porównać** — i tak trzeba to powiedzieć, zamiast
przesuwać bazę po cichu (CLAUDE.md #3.15).

## Przeliczenie na PLN (decyzja 4 planu etapu 8)

Benchmark w walucie obcej jest mnożony przez kurs NBP z tej samej reguły
`max(date) <= D`. Kurs jest częścią realnego wyniku inwestora — porównanie
portfela w PLN z indeksem w USD mieszałoby dwie różne miary. Dla benchmarku
notowanego w PLN mnożnik jest tożsamościowy i wołający po prostu nie podaje
kursów.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date as date_
from decimal import Decimal

__all__ = [
    "BenchmarkPoint",
    "Quote",
    "as_of_values",
    "benchmark_index",
]

_ZERO = Decimal("0")
_INDEX_BASE = Decimal("100")


@dataclass(frozen=True, slots=True)
class Quote:
    """Notowanie albo kurs w jednym dniu — tyle, ile potrzeba do wyrównania.
    Osobny typ zamiast modeli ORM (`Price`, `FxRate`), żeby ten moduł dało
    się testować bez bazy i żeby ta sama funkcja obsłużyła obie tabele."""

    date: date_
    value: Decimal


@dataclass(frozen=True, slots=True)
class BenchmarkPoint:
    """Punkt serii benchmarku wyrównany do daty snapshotu portfela.

    `as_of` to data notowania, z którego wartość faktycznie pochodzi — bywa
    wcześniejsza niż `date` (weekend, święto). Jest w odpowiedzi, bo bez
    niej „benchmark stoi w miejscu" wygląda tak samo jak „giełda była
    zamknięta" (CLAUDE.md #3.15).
    """

    date: date_
    as_of: date_
    value_pln: Decimal
    index: Decimal


def as_of_values(quotes: Sequence[Quote], dates: Sequence[date_]) -> list[Quote | None]:
    """Dla każdej daty z `dates` — ostatnie notowanie nie późniejsze niż ona.

    Obie sekwencje muszą być posortowane rosnąco (`ORDER BY date ASC`
    w repozytorium); funkcja idzie po nich jednym przejściem, `O(n + m)`,
    zamiast szukać binarnie per data. `None` na pozycjach przed pierwszym
    notowaniem — nie ma czym wypełnić i nie wolno podstawiać pierwszego
    późniejszego kursu, bo to byłoby zaglądanie w przyszłość.
    """
    result: list[Quote | None] = []
    latest: Quote | None = None
    position = 0

    for target in dates:
        while position < len(quotes) and quotes[position].date <= target:
            latest = quotes[position]
            position += 1
        result.append(latest)

    return result


def benchmark_index(
    dates: Sequence[date_],
    quotes: Sequence[Quote],
    fx_quotes: Sequence[Quote] | None = None,
    *,
    base: Decimal = _INDEX_BASE,
) -> tuple[BenchmarkPoint, ...]:
    """Seria benchmarku w PLN, znormalizowana do `base` w `dates[0]`.

    `fx_quotes=None` dla benchmarku notowanego w PLN (mnożnik 1).

    Zwraca pustą krotkę, gdy porównanie jest niemożliwe: brak dat, brak
    notowania w dniu startu lub wcześniej, brak kursu w dniu startu, albo
    wartość startowa równa zeru. Wołający zamienia to na jawny komunikat —
    linia benchmarku ma się nie pojawić, zamiast pojawić się przesunięta.

    Dni PO starcie, dla których zabrakło kursu, są pomijane (a nie liczone
    po ostatnim znanym kursie w nieskończoność) tylko wtedy, gdy kursu nie
    ma w ogóle — `as_of_values` z definicji przenosi ostatni znany kurs
    naprzód, co jest tą samą regułą, którą stosuje wycena portfela.
    """
    if not dates:
        return ()

    prices = as_of_values(quotes, dates)
    rates = as_of_values(fx_quotes, dates) if fx_quotes is not None else [None] * len(dates)

    def _value(index: int) -> tuple[date_, Decimal] | None:
        price = prices[index]
        if price is None:
            return None
        if fx_quotes is None:
            return price.date, price.value
        rate = rates[index]
        if rate is None:
            return None
        # `as_of` to data NOTOWANIA, nie kursu: to notowanie decyduje, czy
        # benchmark „stoi", a kurs NBP jest mnożnikiem tej samej wartości.
        return price.date, price.value * rate.value

    first = _value(0)
    if first is None or first[1] == _ZERO:
        return ()
    base_value = first[1]

    points: list[BenchmarkPoint] = []
    for position, target in enumerate(dates):
        valued = _value(position)
        if valued is None:
            # Po udanym `_value(0)` ta gałąź jest nieosiągalna: `as_of_values`
            # niesie ostatnią znaną wartość naprzód, więc skoro punkt startowy
            # się udał, żaden późniejszy nie zwróci `None`. Zostaje jako
            # zabezpieczenie na wypadek zmiany semantyki `as_of_values` —
            # cichy `IndexError`/`None` w środku pętli byłby gorszy niż
            # pominięty punkt. Testy luk w `benchmark_index` sprawdzają
            # zachowanie tej funkcji jako czystej, nie kształt, który
            # produkuje dzisiejszy backend.
            continue
        as_of, value_pln = valued
        points.append(
            BenchmarkPoint(
                date=target,
                as_of=as_of,
                value_pln=value_pln,
                index=base * value_pln / base_value,
            )
        )

    return tuple(points)
