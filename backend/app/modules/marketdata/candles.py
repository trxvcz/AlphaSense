"""Świece OHLC skorygowane o splity i dywidendy (plan krok 45, etap 8).

**Napięcie z zasadą CLAUDE.md #4 rozstrzygnięte tutaj, w jednym miejscu.**
Reguła mówi: wycena i wykresy zawsze na `close_adj`, nigdy na surowym
`close`. Tabela `prices` trzyma jednak **surowe** `open`/`high`/`low`/`close`
i skorygowany wyłącznie `close_adj` (`models.py`) — dostawcy oddają OHLC
w cenach z dnia notowania. Narysowanie świec wprost z tych kolumn złamałoby
zasadę #4 w najbardziej mylący sposób: knoty i korpusy sprzed splitu wisiałyby
kilka razy wyżej niż linia zamknięcia, którą użytkownik zna z pozostałych
wykresów w aplikacji.

**Skalujemy więc całą świecę współczynnikiem `close_adj / close`** — tym
samym, którym dostawca skorygował zamknięcie. Współczynnik jest jednakowy dla
wszystkich czterech cen danego dnia (split i dywidenda przeskalowują cały
dzień, nie samo zamknięcie), więc kształt świecy zostaje nietknięty, zmienia
się tylko poziom. Dla serii bez korekt (Stooq/Finnhub/Binance wpisują
`close_adj := close`, patrz docstring `Price`) współczynnik wynosi dokładnie
`1` i wynik jest identyczny z surowym OHLC.

**Czego świadomie nie robimy:** nie zgadujemy brakujących cen. Wiersz bez
kompletu OHLC albo z `close <= 0` nie daje się skorygować, więc **wypada
z serii i jest policzony** (`skipped`) — ekran ma powiedzieć „tylu dni nie
umiemy pokazać", a nie domalować świecę z `close_adj` w każdym rogu
(CLAUDE.md #3.15). `volume` przechodzi bez zmian: to liczba sztuk, nie cena,
i splitu się nie skaluje współczynnikiem cenowym bez osobnej decyzji.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date as date_
from decimal import ROUND_HALF_UP, Decimal

from app.modules.marketdata.models import Price

# Skala kolumn `NUMERIC(20,8)` — po przeskalowaniu wracamy do niej, żeby
# kontrakt oddawał liczby o tej samej dokładności co reszta cen w API.
_SCALE = Decimal("0.00000001")


@dataclass(frozen=True, slots=True)
class Candle:
    """Jedna świeca, wszystkie ceny **skorygowane** (patrz docstring modułu)."""

    date: date_
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int | None


@dataclass(frozen=True, slots=True)
class CandleSeries:
    """Seria świec plus to, czego w niej NIE ma.

    `skipped` nie jest metryką diagnostyczną, tylko częścią odpowiedzi:
    wykres z dziurą wygląda identycznie jak wykres kompletny, więc liczba
    pominiętych dni musi dojechać do UI (CLAUDE.md #3.15).
    """

    candles: list[Candle]
    skipped: int


def _quantize(value: Decimal) -> Decimal:
    return value.quantize(_SCALE, rounding=ROUND_HALF_UP)


def adjusted_candle(price: Price) -> Candle | None:
    """Jeden wiersz `prices` → świeca skorygowana, albo `None`.

    `None` dla wiersza bez kompletu OHLC i dla `close <= 0` (współczynnika
    nie da się policzyć — dzielenie przez zero albo przez cenę ujemną, która
    i tak jest artefaktem danych).
    """
    if price.open is None or price.high is None or price.low is None or price.close is None:
        return None
    if price.close <= 0:
        return None

    factor = price.close_adj / price.close
    return Candle(
        date=price.date,
        open=_quantize(price.open * factor),
        high=_quantize(price.high * factor),
        low=_quantize(price.low * factor),
        # Zamknięcie bierzemy wprost z `close_adj`, a nie z `close * factor`:
        # matematycznie to to samo, ale bez błędu zaokrąglenia dzielenia
        # i mnożenia — a to jest liczba, którą użytkownik widzi także na
        # wykresie wartości portfela i w wycenie pozycji.
        close=_quantize(price.close_adj),
        volume=price.volume,
    )


def build_series(prices: list[Price]) -> CandleSeries:
    """Cała seria. Funkcja czysta, bez I/O — testowana na policzonych ręcznie
    przypadkach w `tests/unit/test_candles.py` (CLAUDE.md §8)."""
    candles: list[Candle] = []
    skipped = 0
    for price in prices:
        candle = adjusted_candle(price)
        if candle is None:
            skipped += 1
        else:
            candles.append(candle)
    return CandleSeries(candles=candles, skipped=skipped)
