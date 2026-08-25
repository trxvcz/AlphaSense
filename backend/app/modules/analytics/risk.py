"""Metryki ryzyka portfela ze snapshotów (plan krok 41b, etap 8).

Czysta matematyka na `Decimal` — bez sesji bazy, bez I/O, bez Pydantic, tak
jak `analytics.returns` (krok 40) i `analytics.benchmark` (krok 42). Wołający
(`analytics.service.risk`) podaje gotowe serie i dostaje liczby.

## Wejściem są OGNIWA, nie `value_pln`

Wszystko liczy się z serii z `analytics.returns`: zmienność i Sharpe z
`DailyReturn`, drawdown z indeksu łańcuchowego (`IndexPoint.index`). Nigdy
z `value_pln` — wpłata podnosi wartość portfela bez żadnego zysku, więc
drawdown liczony na wartości pokazałby dopłatę jako wyjście z obsunięcia,
a zmienność liczyłaby dopłatę jako zmienność rynku (ADR-101, CLAUDE.md #1).

## Jedno ogniwo = jedna obserwacja

Ogniwo bywa rozpięte na więcej niż dobę (weekend, brak przebiegu workera —
patrz `returns`, „Dziura w serii łączy ogniwo"). Traktujemy je mimo to jako
jedną obserwację i annualizujemy przez `√252`. Alternatywa — ważenie ogniw
długością — wymagałaby kalendarza sesji per rynek, którego portfel
wielorynkowy i tak nie ma jednego; a przy regularnie działającym workerze
różnica jest żadna. Liczba obserwacji jedzie w odpowiedzi (`observations`),
więc „zmienność z 30 ogniw" da się odróżnić od „z 250".

## Za mało danych → `None`, nigdy liczba

Poniżej `MIN_OBSERVATIONS` każda z tych metryk jest szumem, a nie
oszacowaniem. Zwracamy `None` i powód, zamiast liczby, której nie da się
obronić (CLAUDE.md #3.15). To samo dotyczy braku stopy referencyjnej:
Sharpe bez stopy wolnej od ryzyka jest niepoliczalny, a podstawienie zera
dałoby wynik nie do odróżnienia od policzonego na prawdziwych danych.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date as date_
from decimal import Decimal

from app.modules.analytics.benchmark import Quote, as_of_values
from app.modules.analytics.returns import DailyReturn, IndexPoint, chain_link

__all__ = [
    "MIN_OBSERVATIONS",
    "TRADING_DAYS_PER_YEAR",
    "Drawdown",
    "MonthlyReturn",
    "UnderwaterPoint",
    "beta",
    "max_drawdown",
    "monthly_returns",
    "risk_free_daily",
    "sharpe",
    "underwater",
    "volatility",
]

_ZERO = Decimal("0")
_ONE = Decimal("1")

# Liczba sesji w roku używana do annualizacji (√252 dla odchylenia, /252 dla
# stopy wolnej od ryzyka). Konwencja rynkowa, nie wynik pomiaru — jedziemy
# z nią jawnie, żeby ta sama liczba nie została zapisana w trzech miejscach.
TRADING_DAYS_PER_YEAR = 252

# Minimalna liczba ogniw, poniżej której nie podajemy metryki. Dwadzieścia
# to około miesiąca sesji: odchylenie z pięciu obserwacji ma błąd
# oszacowania większy niż samo oszacowanie, a wyświetlone bez ostrzeżenia
# wygląda dokładnie tak samo jak policzone z roku.
MIN_OBSERVATIONS = 20

_SQRT_TRADING_DAYS = Decimal(TRADING_DAYS_PER_YEAR).sqrt()


@dataclass(frozen=True, slots=True)
class Drawdown:
    """Największe obsunięcie i to, kiedy się wydarzyło.

    `value` jest **ujemne** (`-0.23` = obsunięcie o 23%) albo zero dla serii,
    która nigdy nie spadła poniżej szczytu — znak niesie kierunek, więc UI
    nie musi zgadywać, czy „23%" to spadek, czy wzrost.

    `recovered_at` to pierwszy dzień, w którym indeks wrócił do szczytu
    z `peak_date`; `None` znaczy „portfel jeszcze nie odrobił". Rozróżnienie
    jest istotne: obsunięcie sprzed trzech lat, odrobione, to co innego niż
    to samo obsunięcie trwające do dziś.
    """

    value: Decimal
    peak_date: date_
    trough_date: date_
    recovered_at: date_ | None


@dataclass(frozen=True, slots=True)
class UnderwaterPoint:
    """Punkt wykresu underwater: o ile procent poniżej dotychczasowego
    szczytu stoi indeks w danym dniu (`0` na szczycie, wartości ujemne
    poniżej)."""

    date: date_
    value: Decimal


@dataclass(frozen=True, slots=True)
class MonthlyReturn:
    """Zwrot za jeden miesiąc kalendarzowy, złożony z ogniw tego miesiąca.

    `links` jest tu z tego samego powodu co w `ReturnSeries`: miesiąc
    złożony z trzech ogniw i miesiąc z dwudziestu wyglądają na heatmapie
    identycznie, a znaczą co innego. Heatmapa ma to oznaczyć.
    """

    year: int
    month: int
    ret: Decimal
    links: int


def _mean(values: Sequence[Decimal]) -> Decimal:
    return sum(values, _ZERO) / Decimal(len(values))


def _stdev(values: Sequence[Decimal]) -> Decimal | None:
    """Odchylenie standardowe **z próby** (dzielnik `n - 1`), nie z populacji.

    Seria zwrotów jest próbką z nieznanego rozkładu, a nie całą populacją —
    dzielnik `n` zaniżałby zmienność systematycznie, najmocniej dokładnie
    tam, gdzie danych jest mało, czyli tam, gdzie i tak jest najgorzej.
    """
    if len(values) < 2:
        return None
    average = _mean(values)
    variance = sum(((value - average) ** 2 for value in values), _ZERO) / Decimal(len(values) - 1)
    return variance.sqrt()


def risk_free_daily(
    rates: Sequence[Quote],
    dates: Sequence[date_],
    *,
    periods_per_year: int = TRADING_DAYS_PER_YEAR,
) -> list[Decimal | None]:
    """Dzienna stopa wolna od ryzyka dla każdej daty z `dates`.

    `rates` to zmiany stopy referencyjnej NBP (`Quote(date=effective_from,
    value=ułamek roczny)`, krok 41a) — obowiązywanie „do następnej decyzji
    RPP" realizuje `as_of_values`, ta sama funkcja, która wyrównuje notowania
    benchmarku do dat snapshotów. `None` przed pierwszą znaną stopą: nie ma
    czym wypełnić i nie wolno brać pierwszej późniejszej, bo to byłoby
    zaglądanie w przyszłość.

    Dzielimy stopę roczną przez `periods_per_year` (prosta konwersja, nie
    `(1+r)^(1/252)-1`): przy stopach rzędu kilku procent różnica między tymi
    dwoma jest o rzędy wielkości mniejsza niż błąd oszacowania samej
    zmienności, a konwencja rynkowa dla Sharpe'a jest prosta.
    """
    divisor = Decimal(periods_per_year)
    return [
        None if quote is None else quote.value / divisor for quote in as_of_values(rates, dates)
    ]


def volatility(
    returns: Sequence[Decimal], *, periods_per_year: int = TRADING_DAYS_PER_YEAR
) -> Decimal | None:
    """Annualizowana zmienność (`σ · √252`) albo `None` przy zbyt krótkiej serii."""
    if len(returns) < MIN_OBSERVATIONS:
        return None
    deviation = _stdev(returns)
    if deviation is None:
        return None
    root = (
        _SQRT_TRADING_DAYS
        if periods_per_year == TRADING_DAYS_PER_YEAR
        else Decimal(periods_per_year).sqrt()
    )
    return deviation * root


def sharpe(
    returns: Sequence[Decimal],
    risk_free: Sequence[Decimal | None],
    *,
    periods_per_year: int = TRADING_DAYS_PER_YEAR,
) -> Decimal | None:
    """Annualizowany Sharpe: `mean(r - rf) / stdev(r - rf) · √252`.

    `risk_free` to stopa **dzienna** dla tych samych obserwacji co `returns`
    (ta sama długość, `risk_free_daily`). Obserwacje, dla których stopy nie
    znamy (`None`), są **odrzucane w parze** — liczyć zwrot z dnia, dla
    którego nie ma stopy, znaczyłoby po cichu przyjąć rf = 0 dla tego dnia.

    `None`, gdy po odrzuceniu zostaje mniej niż `MIN_OBSERVATIONS` par albo
    gdy odchylenie nadwyżek wynosi zero (portfel bez żadnej zmienności — iloraz
    nie istnieje, a nie „jest nieskończony").
    """
    if len(returns) != len(risk_free):
        raise ValueError("`returns` i `risk_free` muszą mieć tę samą długość")
    excess = [ret - rf for ret, rf in zip(returns, risk_free, strict=True) if rf is not None]
    if len(excess) < MIN_OBSERVATIONS:
        return None
    deviation = _stdev(excess)
    if deviation is None or deviation == _ZERO:
        return None
    root = (
        _SQRT_TRADING_DAYS
        if periods_per_year == TRADING_DAYS_PER_YEAR
        else Decimal(periods_per_year).sqrt()
    )
    return _mean(excess) / deviation * root


def beta(portfolio: Sequence[Decimal], benchmark: Sequence[Decimal]) -> Decimal | None:
    """Beta portfela względem benchmarku: `cov(p, b) / var(b)`.

    Obie serie muszą być **sparowane po dacie** przez wołającego (ten sam
    dzień na tej samej pozycji) — ta funkcja nie zna dat i nie ma jak tego
    sprawdzić, a przesunięcie serii o jeden dzień dałoby betę wyglądającą
    normalnie i nieprawdziwą. Stąd wyrównanie robi `service.risk`, a nie tu.

    `None` przy zbyt krótkiej serii albo gdy benchmark się nie ruszał
    (`var == 0`) — dzielenie przez zero to nie „beta nieskończona", tylko
    „beta niepoliczalna".
    """
    if len(portfolio) != len(benchmark):
        raise ValueError("`portfolio` i `benchmark` muszą mieć tę samą długość")
    if len(portfolio) < MIN_OBSERVATIONS:
        return None
    mean_p = _mean(portfolio)
    mean_b = _mean(benchmark)
    n = Decimal(len(portfolio) - 1)
    covariance = (
        sum(((p - mean_p) * (b - mean_b) for p, b in zip(portfolio, benchmark, strict=True)), _ZERO)
        / n
    )
    variance = sum(((b - mean_b) ** 2 for b in benchmark), _ZERO) / n
    if variance == _ZERO:
        return None
    return covariance / variance


def underwater(points: Sequence[IndexPoint]) -> tuple[UnderwaterPoint, ...]:
    """Seria „o ile poniżej szczytu" dla każdego punktu indeksu.

    Szczyt jest biegnący (`running max`), więc pierwszy punkt zawsze daje
    zero, a nowy szczyt zeruje serię — to jest dokładnie ten wykres, który
    pokazuje, jak długo trwało obsunięcie, a nie tylko jak głębokie było.
    """
    result: list[UnderwaterPoint] = []
    peak: Decimal | None = None

    for point in points:
        if peak is None or point.index > peak:
            peak = point.index
        # Indeks zaczyna się od dodatniej bazy i mnoży się przez `1 + r`,
        # więc zero oznaczałoby portfel wart dokładnie nic; zabezpieczenie
        # jest tu po to, żeby taka seria nie wywaliła całej odpowiedzi.
        value = _ZERO if peak == _ZERO else point.index / peak - _ONE
        result.append(UnderwaterPoint(date=point.date, value=value))

    return tuple(result)


def max_drawdown(points: Sequence[IndexPoint]) -> Drawdown | None:
    """Największe obsunięcie indeksu łańcuchowego wraz z datami.

    Jedno przejście: pamiętamy biegnący szczyt i najgłębsze dotąd
    obsunięcie. `None` dla pustej serii — portfel bez historii nie ma
    obsunięcia równego zeru, on go po prostu nie ma.

    Seria bez ani jednego spadku daje `Drawdown(value=0, ...)` z datami
    pierwszego punktu: zero jest tu prawdziwą odpowiedzią („nigdy nie
    spadł"), w odróżnieniu od braku danych.
    """
    if not points:
        return None

    peak = points[0].index
    peak_date = points[0].date
    worst = _ZERO
    worst_peak_date = points[0].date
    worst_trough_date = points[0].date

    for point in points:
        if point.index > peak:
            peak = point.index
            peak_date = point.date
        drop = _ZERO if peak == _ZERO else point.index / peak - _ONE
        if drop < worst:
            worst = drop
            worst_peak_date = peak_date
            worst_trough_date = point.date

    recovered_at: date_ | None = None
    if worst < _ZERO:
        peak_value = next(p.index for p in points if p.date == worst_peak_date)
        recovered_at = next(
            (p.date for p in points if p.date > worst_trough_date and p.index >= peak_value),
            None,
        )

    return Drawdown(
        value=worst,
        peak_date=worst_peak_date,
        trough_date=worst_trough_date,
        recovered_at=recovered_at,
    )


def monthly_returns(returns: Sequence[DailyReturn]) -> tuple[MonthlyReturn, ...]:
    """Zwroty miesięczne złożone z ogniw, rosnąco po miesiącu.

    Składamy ogniwa (`chain_link`), a **nie** dzielimy indeksu z końca
    miesiąca przez indeks z początku. Różnica jest w miesiącach ze zmianą
    składu: indeks stoi na zerwanym ogniwie, więc iloraz krańców
    przypisałby miesiącowi zwrot za dni, których nie znamy. Skład ogniw
    liczy dokładnie to, co wiemy.

    Miesiąc bez ani jednego ogniwa (portfel bez snapshotów) **nie pojawia
    się** w wyniku — heatmapa ma pokazać dziurę, a nie zero.
    """
    buckets: dict[tuple[int, int], list[Decimal]] = {}
    for link in returns:
        buckets.setdefault((link.date.year, link.date.month), []).append(link.ret)

    return tuple(
        MonthlyReturn(year=year, month=month, ret=chain_link(values), links=len(values))
        for (year, month), values in sorted(buckets.items())
    )
