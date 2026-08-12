"""Zwroty portfela ze snapshotów `portfolio_valuations` (plan krok 40, etap 8).

Czysta matematyka na `Decimal` — bez sesji bazy, bez I/O, bez Pydantic.
Wołający (`analytics.service.performance`) podaje gotową serię punktów i
dostaje serię zwrotów oraz zwrot za okres. Dzięki temu testy liczą na
znanych liczbach, bez mocków bazy (CLAUDE.md §8).

## Dlaczego łańcuch, a nie `V_koniec / V_start - 1`

Snapshoty są append-only i **nie znają przepływów** (ADR-101, CLAUDE.md #1 —
transakcje to odsunięty Etap 21). Dzień, w którym użytkownik dopisał pozycję,
podnosi `value_pln` bez żadnego zysku: portfel wart 1000 PLN po dopisaniu
pozycji za 500 PLN pokazuje snapshot 1500 PLN. Iloraz krańców policzyłby z
tego +50%.

Stąd łańcuch ogniw `r_t = V_t / V_{t-1} - 1` i **zerwanie ogniwa** w dniu
`composition_change=true`. Zerwanie dotyczy wyłącznie przejścia `t-1 → t`,
a nie obu dni: `V_t` zostaje bazą dla `r_{t+1}`, bo w nowym składzie portfel
już normalnie żyje. Skasowanie obu dni wycięłoby z serii prawdziwy zwrot
następnego dnia (skill `analityka-struktury`, sekcja „Zwroty").

## Dziura w serii łączy ogniwo (decyzja 6 planu etapu 8)

Weekend, święto i dzień bez przebiegu workera wyglądają w tabeli identycznie —
jako brak wiersza. Zrywanie ogniwa przy każdej przerwie wycięłoby przy
nieregularnym workerze większość okresu i **zaniżało zwrot bez ostrzeżenia**,
bo iloczyn mniejszej liczby ogniw jest cichy: nic w odpowiedzi nie mówiłoby,
że zamiast roku policzono trzy tygodnie. Dlatego przerwa łączy, a odpowiedź
niesie liczniki — „zwrot za 1Y z 40 ogniw" ma wyglądać inaczej niż ten sam
zwrot z 250.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date as date_
from decimal import Decimal

__all__ = [
    "DailyReturn",
    "IndexPoint",
    "ReturnSeries",
    "ValuationPoint",
    "chain_index",
    "chain_link",
    "daily_returns",
    "period_return",
]

_ONE = Decimal("1")
_ZERO = Decimal("0")
_INDEX_BASE = Decimal("100")


@dataclass(frozen=True, slots=True)
class ValuationPoint:
    """Jeden snapshot na wejściu — tyle z `PortfolioValuation`, ile potrzeba
    do policzenia zwrotu. Osobny typ zamiast modelu ORM, żeby ten moduł dało
    się testować bez bazy."""

    date: date_
    value_pln: Decimal
    composition_change: bool


@dataclass(frozen=True, slots=True)
class DailyReturn:
    """Jedno ogniwo łańcucha: zwrot z dnia poprzedzającego na `date`.

    `date` to dzień KOŃCA ogniwa — ten, w którym znamy `V_t`. `previous_date`
    bywa odległy o więcej niż jeden dzień (weekend, brak przebiegu workera)
    i właśnie dlatego jest tu jawnie: bez niego nie da się odróżnić zwrotu
    dziennego od zwrotu za trzy dni, a wykres rysowałby oba tak samo.
    """

    date: date_
    previous_date: date_
    value_pln: Decimal
    ret: Decimal


@dataclass(frozen=True, slots=True)
class IndexPoint:
    """Punkt serii wykresu wyników: wartość portfela obok indeksu
    łańcuchowego. `ret=None` oznacza ogniwo zerwane albo pierwszy punkt —
    w obu przypadkach zwrotu za ten dzień NIE ZNAMY (patrz `chain_index`)."""

    date: date_
    value_pln: Decimal
    ret: Decimal | None
    index: Decimal


@dataclass(frozen=True, slots=True)
class ReturnSeries:
    """Seria ogniw plus rachunek z tego, czego w niej NIE ma.

    Liczniki nie są ozdobą: iloczyn ogniw wygląda tak samo policzony z 250
    ogniw i z 40, a różnica między nimi to różnica między zwrotem rocznym
    a zwrotem z półtora miesiąca. Rozdzielone po powodzie, bo znaczą co
    innego — `skipped_composition_change` to działanie zamierzone (ADR-101),
    `skipped_zero_base` to sygnał, że coś jest nie tak z danymi.
    """

    returns: tuple[DailyReturn, ...]
    skipped_composition_change: int
    skipped_zero_base: int

    @property
    def links(self) -> int:
        """Liczba ogniw, z których faktycznie policzono zwrot."""
        return len(self.returns)

    @property
    def skipped(self) -> int:
        return self.skipped_composition_change + self.skipped_zero_base


def _link(previous: ValuationPoint, current: ValuationPoint) -> DailyReturn | None:
    """Ogniwo `previous → current` albo `None`, gdy go nie ma.

    Jedno miejsce z regułą zrywania — `daily_returns` i `chain_index` muszą
    się zgadzać co do tego, które ogniwa istnieją, inaczej seria na wykresie
    rozjechałaby się ze zwrotem pod nim.
    """
    if current.composition_change:
        # Różnica wartości zawiera wpłatę/dopisanie pozycji, nie wynik.
        # `current` zostaje bazą następnego ogniwa (patrz docstring modułu).
        return None
    if previous.value_pln == _ZERO:
        # Zwrot z zerowej bazy jest nieokreślony, nie nieskończony. W praktyce
        # dzień po pustym portfelu ma `composition_change` i wypada wyżej;
        # ten warunek broni przed dzieleniem przez zero, gdyby flaga nie doszła.
        return None
    return DailyReturn(
        date=current.date,
        previous_date=previous.date,
        value_pln=current.value_pln,
        ret=current.value_pln / previous.value_pln - _ONE,
    )


def daily_returns(points: Sequence[ValuationPoint]) -> ReturnSeries:
    """Zamienia serię snapshotów (rosnąco po dacie) w serię ogniw.

    Wejście musi być posortowane rosnąco — sortowanie jest zadaniem
    zapytania SQL (`ORDER BY date ASC` w `repository.list_valuations`), nie
    tej funkcji: ciche przesortowanie tutaj ukryłoby błąd wołającego.

    Zero punktów albo jeden punkt daje pustą serię, nie błąd — portfel
    założony wczoraj po prostu nie ma jeszcze zwrotu.
    """
    returns: list[DailyReturn] = []
    skipped_composition = 0
    skipped_zero = 0

    for previous, current in zip(points, points[1:], strict=False):
        link = _link(previous, current)
        if link is not None:
            returns.append(link)
        elif current.composition_change:
            skipped_composition += 1
        else:
            skipped_zero += 1

    return ReturnSeries(
        returns=tuple(returns),
        skipped_composition_change=skipped_composition,
        skipped_zero_base=skipped_zero,
    )


def chain_index(
    points: Sequence[ValuationPoint], *, base: Decimal = _INDEX_BASE
) -> tuple[IndexPoint, ...]:
    """Indeks łańcuchowy o bazie `base` w pierwszym punkcie serii.

    To jest seria, którą rysuje wykres wyników — **nie** `value_pln`.
    Różnica jest cała w dniach zmiany składu: wpłata podnosi `value_pln`,
    ale nie indeks, bo portfel nic na niej nie zarobił. Ta sama seria jest
    podstawą drawdownu w kroku 41 (drawdown liczony na `value_pln` pokazałby
    wpłatę jako wyjście z obsunięcia) i porównania z benchmarkiem w kroku 42
    (obie serie znormalizowane do 100).

    Na zerwanym ogniwie indeks **stoi**, a `ret` jest `None`: nie znamy
    zwrotu za ten dzień, więc nie wolno go ani zgadywać, ani podstawiać zera
    — zero to twierdzenie „portfel nic nie zarobił", a my po prostu nie wiemy.
    """
    if not points:
        return ()

    result = [IndexPoint(date=points[0].date, value_pln=points[0].value_pln, ret=None, index=base)]
    current_index = base

    for previous, current in zip(points, points[1:], strict=False):
        link = _link(previous, current)
        if link is not None:
            current_index *= _ONE + link.ret
        result.append(
            IndexPoint(
                date=current.date,
                value_pln=current.value_pln,
                ret=link.ret if link is not None else None,
                index=current_index,
            )
        )

    return tuple(result)


def chain_link(returns: Iterable[Decimal]) -> Decimal:
    """Składa zwroty w jeden: `Π(1 + rᵢ) - 1`.

    Pusty ciąg daje `0` (brak ogniw to brak zwrotu, nie błąd) — jest to
    zarazem element neutralny mnożenia po odjęciu jedynki, więc funkcja
    zostaje spójna przy sklejaniu podokresów.

    Bez zaokrąglania: kwantyzacja należy do warstwy prezentacji
    (`service.performance`). Zaokrąglenie każdego ogniwa przed mnożeniem
    kumulowałoby błąd przez wszystkie 250 dni roku.
    """
    product = _ONE
    for ret in returns:
        product *= _ONE + ret
    return product - _ONE


def period_return(points: Sequence[ValuationPoint]) -> tuple[Decimal, ReturnSeries]:
    """Zwrot za cały okres i seria, z której powstał.

    Zwracane razem celowo — sam zwrot bez `links` jest liczbą bez kontekstu
    (patrz docstring `ReturnSeries`), a wołający i tak potrzebuje obu.
    """
    series = daily_returns(points)
    return chain_link(r.ret for r in series.returns), series
