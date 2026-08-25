"""Testy `app.modules.analytics.risk` (plan krok 41b, etap 8).

Jednostkowe, bez bazy i bez mocków — to czysta matematyka, więc liczy się
na znanych liczbach (CLAUDE.md §8).

**Skąd wartości oczekiwane.** Tam, gdzie wynik da się policzyć w głowie
(drawdown, underwater, grupowanie miesięczne), jest wpisany wprost. Tam,
gdzie nie (odchylenie, kowariancja), porównujemy z **niezależną
implementacją** ze `statistics` w bibliotece standardowej, a nie z liczbą
przepisaną z naszego własnego kodu — test, który powtarza implementację,
przechodzi także wtedy, gdy implementacja jest błędna.
"""

from __future__ import annotations

import math
import statistics
from datetime import date
from decimal import Decimal

import pytest

from app.modules.analytics.benchmark import Quote
from app.modules.analytics.returns import DailyReturn, IndexPoint
from app.modules.analytics.risk import (
    MIN_OBSERVATIONS,
    TRADING_DAYS_PER_YEAR,
    beta,
    max_drawdown,
    monthly_returns,
    risk_free_daily,
    sharpe,
    underwater,
    volatility,
)

_TOLERANCE = 1e-12


def _returns(values: list[str]) -> list[Decimal]:
    return [Decimal(v) for v in values]


def _alternating(n: int, magnitude: str = "0.01") -> list[Decimal]:
    """Seria `+m, -m, +m, ...` — średnia zero, znane odchylenie."""
    step = Decimal(magnitude)
    return [step if i % 2 == 0 else -step for i in range(n)]


def _index_series(values: list[str], *, start: date = date(2026, 1, 1)) -> list[IndexPoint]:
    """Punkty indeksu o kolejnych datach; `ret`/`value_pln` nieistotne dla
    drawdownu, który patrzy wyłącznie na `index`."""
    return [
        IndexPoint(
            date=date.fromordinal(start.toordinal() + offset),
            value_pln=Decimal(value),
            ret=None,
            index=Decimal(value),
        )
        for offset, value in enumerate(values)
    ]


# --- zmienność --------------------------------------------------------------


def test_volatility_matches_sample_stdev_times_sqrt_252() -> None:
    values = _alternating(40)

    result = volatility(values)

    assert result is not None
    expected = statistics.stdev(float(v) for v in values) * math.sqrt(TRADING_DAYS_PER_YEAR)
    assert float(result) == pytest.approx(expected, rel=_TOLERANCE)


def test_volatility_uses_sample_divisor_not_population() -> None:
    """Dzielnik `n - 1`, nie `n` — inaczej zmienność jest zaniżana."""
    values = _alternating(40)

    result = volatility(values)

    assert result is not None
    population = statistics.pstdev(float(v) for v in values) * math.sqrt(TRADING_DAYS_PER_YEAR)
    assert float(result) != pytest.approx(population, rel=1e-6)


def test_volatility_below_minimum_observations_is_none() -> None:
    """19 ogniw to za mało — `None`, nie liczba nie do obrony."""
    assert volatility(_alternating(MIN_OBSERVATIONS - 1)) is None
    assert volatility(_alternating(MIN_OBSERVATIONS)) is not None


def test_volatility_of_flat_series_is_zero() -> None:
    """Portfel, który się nie ruszał, ma zmienność zero — to jest wynik, nie brak."""
    result = volatility([Decimal("0")] * 30)

    assert result == Decimal("0")


# --- Sharpe -----------------------------------------------------------------


def test_sharpe_matches_manual_formula() -> None:
    values = _alternating(40)
    rf = [Decimal("0.0375") / TRADING_DAYS_PER_YEAR] * 40

    result = sharpe(values, list(rf))

    assert result is not None
    excess = [float(v - r) for v, r in zip(values, rf, strict=True)]
    expected = (
        statistics.fmean(excess) / statistics.stdev(excess) * math.sqrt(TRADING_DAYS_PER_YEAR)
    )
    assert float(result) == pytest.approx(expected, rel=_TOLERANCE)


def test_sharpe_drops_observations_without_known_rate() -> None:
    """Dzień bez stopy wypada **w parze** ze swoim zwrotem.

    Zostawienie zwrotu bez stopy znaczyłoby przyjęcie rf = 0 dla tego dnia —
    po cichu, bez śladu w wyniku.
    """
    values = _alternating(40)
    rf: list[Decimal | None] = [Decimal("0.0375") / TRADING_DAYS_PER_YEAR] * 40
    rf[0] = None
    rf[5] = None

    result = sharpe(values, rf)

    assert result is not None
    paired = [(float(v), float(r)) for v, r in zip(values, rf, strict=True) if r is not None]
    excess = [v - r for v, r in paired]
    expected = (
        statistics.fmean(excess) / statistics.stdev(excess) * math.sqrt(TRADING_DAYS_PER_YEAR)
    )
    assert float(result) == pytest.approx(expected, rel=_TOLERANCE)


def test_sharpe_is_none_when_too_few_dates_have_a_rate() -> None:
    """40 zwrotów, ale stopa znana tylko dla 19 z nich → `None`."""
    values = _alternating(40)
    rf: list[Decimal | None] = [None] * 40
    for i in range(MIN_OBSERVATIONS - 1):
        rf[i] = Decimal("0.0001")

    assert sharpe(values, rf) is None


def test_sharpe_of_flat_series_is_none_not_infinity() -> None:
    """Zerowe odchylenie nadwyżek → `None`. Iloraz nie istnieje."""
    values = [Decimal("0.0001")] * 30
    rf: list[Decimal | None] = [Decimal("0.0001")] * 30

    assert sharpe(values, rf) is None


def test_sharpe_length_mismatch_raises() -> None:
    with pytest.raises(ValueError):
        sharpe(_alternating(30), [Decimal("0")] * 29)


# --- stopa wolna od ryzyka --------------------------------------------------


def test_risk_free_daily_carries_rate_forward_until_next_decision() -> None:
    """`max(effective_from) <= D` — stopa obowiązuje do następnej decyzji RPP."""
    rates = [
        Quote(date=date(2025, 12, 4), value=Decimal("0.04")),
        Quote(date=date(2026, 3, 5), value=Decimal("0.0375")),
    ]
    dates = [date(2026, 1, 15), date(2026, 3, 4), date(2026, 3, 5), date(2026, 6, 1)]

    result = risk_free_daily(rates, dates)

    divisor = Decimal(TRADING_DAYS_PER_YEAR)
    assert result == [
        Decimal("0.04") / divisor,
        Decimal("0.04") / divisor,
        Decimal("0.0375") / divisor,
        Decimal("0.0375") / divisor,
    ]


def test_risk_free_daily_before_first_known_rate_is_none() -> None:
    """Przed pierwszą znaną stopą `None` — nie wolno brać późniejszej.

    Podstawienie pierwszej późniejszej stopy byłoby zaglądaniem w przyszłość:
    Sharpe za 2019 rok liczony stopą z 2026 nie jest przybliżeniem, tylko
    innym wynikiem.
    """
    rates = [Quote(date=date(2026, 3, 5), value=Decimal("0.0375"))]

    result = risk_free_daily(rates, [date(2026, 3, 4), date(2026, 3, 5)])

    assert result[0] is None
    assert result[1] == Decimal("0.0375") / Decimal(TRADING_DAYS_PER_YEAR)


def test_risk_free_daily_with_no_rates_is_all_none() -> None:
    assert risk_free_daily([], [date(2026, 3, 5)]) == [None]


# --- beta -------------------------------------------------------------------


def test_beta_of_series_identical_to_benchmark_is_one() -> None:
    values = _alternating(40)

    assert beta(values, list(values)) == Decimal("1")


def test_beta_of_double_amplitude_is_two() -> None:
    benchmark = _alternating(40)
    portfolio = [v * 2 for v in benchmark]

    result = beta(portfolio, benchmark)

    # Nie `== Decimal("2")`: dzielenie `Decimal` obcina do 28 cyfr znaczących,
    # więc wychodzi 1.999...9. To jest właściwość arytmetyki dziesiętnej, a nie
    # błąd metryki — porównujemy z dokładnością, która ma sens dla bety.
    assert result is not None
    assert result.quantize(Decimal("0.0001")) == Decimal("2.0000")


def test_beta_matches_covariance_over_variance() -> None:
    portfolio = _returns([str(Decimal(i % 7) / 1000 - Decimal("0.003")) for i in range(40)])
    benchmark = _returns([str(Decimal(i % 5) / 1000 - Decimal("0.002")) for i in range(40)])

    result = beta(portfolio, benchmark)

    assert result is not None
    p = [float(v) for v in portfolio]
    b = [float(v) for v in benchmark]
    expected = statistics.covariance(p, b) / statistics.variance(b)
    assert float(result) == pytest.approx(expected, rel=1e-9)


def test_beta_against_motionless_benchmark_is_none() -> None:
    """Wariancja zero → beta niepoliczalna, nie nieskończona."""
    assert beta(_alternating(40), [Decimal("0")] * 40) is None


def test_beta_below_minimum_observations_is_none() -> None:
    values = _alternating(MIN_OBSERVATIONS - 1)
    assert beta(values, list(values)) is None


def test_beta_length_mismatch_raises() -> None:
    with pytest.raises(ValueError):
        beta(_alternating(30), _alternating(29))


# --- drawdown ---------------------------------------------------------------


def test_max_drawdown_finds_deepest_drop_with_dates() -> None:
    # 100 → 120 (szczyt) → 90 (dno, -25%) → 130. Drugie, płytsze obsunięcie
    # (130 → 125) nie może wygrać z pierwszym.
    points = _index_series(["100", "120", "90", "130", "125"])

    result = max_drawdown(points)

    assert result is not None
    assert result.value == Decimal("-0.25")
    assert result.peak_date == date(2026, 1, 2)
    assert result.trough_date == date(2026, 1, 3)


def test_max_drawdown_reports_recovery_date() -> None:
    """Odrobienie = powrót do wartości szczytu, nie do dna."""
    points = _index_series(["100", "120", "90", "115", "120"])

    result = max_drawdown(points)

    assert result is not None
    assert result.recovered_at == date(2026, 1, 5)


def test_max_drawdown_not_recovered_is_none() -> None:
    """Obsunięcie trwające do dziś to co innego niż odrobione."""
    points = _index_series(["100", "120", "90", "110"])

    result = max_drawdown(points)

    assert result is not None
    assert result.recovered_at is None


def test_max_drawdown_of_rising_series_is_zero_not_none() -> None:
    """Zero to prawdziwa odpowiedź („nigdy nie spadł"), nie brak danych."""
    result = max_drawdown(_index_series(["100", "110", "120"]))

    assert result is not None
    assert result.value == Decimal("0")
    assert result.recovered_at is None


def test_max_drawdown_of_empty_series_is_none() -> None:
    assert max_drawdown([]) is None


# --- underwater -------------------------------------------------------------


def test_underwater_is_zero_at_every_new_peak() -> None:
    points = _index_series(["100", "120", "90", "130"])

    result = underwater(points)

    assert [p.value for p in result] == [
        Decimal("0"),
        Decimal("0"),
        Decimal("-0.25"),
        Decimal("0"),
    ]


def test_underwater_keeps_one_point_per_index_point() -> None:
    points = _index_series(["100", "90", "95", "80"])

    result = underwater(points)

    assert [p.date for p in result] == [p.date for p in points]


def test_underwater_of_empty_series_is_empty() -> None:
    assert underwater([]) == ()


# --- zwroty miesięczne ------------------------------------------------------


def _link(day: date, ret: str) -> DailyReturn:
    return DailyReturn(
        date=day,
        previous_date=date.fromordinal(day.toordinal() - 1),
        value_pln=Decimal("1000"),
        ret=Decimal(ret),
    )


def test_monthly_returns_chain_links_within_each_month() -> None:
    links = [
        _link(date(2026, 1, 10), "0.1"),
        _link(date(2026, 1, 20), "0.1"),
        _link(date(2026, 2, 10), "-0.5"),
    ]

    result = monthly_returns(links)

    assert [(m.year, m.month) for m in result] == [(2026, 1), (2026, 2)]
    # 1.1 * 1.1 - 1 = 0.21 dokładnie — składanie, nie sumowanie (0.2).
    assert result[0].ret == Decimal("0.21")
    assert result[0].links == 2
    assert result[1].ret == Decimal("-0.5")


def test_monthly_returns_skips_months_without_links() -> None:
    """Miesiąc bez ogniw znika z wyniku — heatmapa ma pokazać dziurę, nie zero."""
    links = [_link(date(2026, 1, 10), "0.1"), _link(date(2026, 3, 10), "0.1")]

    result = monthly_returns(links)

    assert [(m.year, m.month) for m in result] == [(2026, 1), (2026, 3)]


def test_monthly_returns_are_sorted_chronologically_across_years() -> None:
    links = [_link(date(2026, 1, 10), "0.1"), _link(date(2025, 12, 10), "0.1")]

    result = monthly_returns(links)

    assert [(m.year, m.month) for m in result] == [(2025, 12), (2026, 1)]


def test_monthly_returns_of_empty_series_is_empty() -> None:
    assert monthly_returns([]) == ()
