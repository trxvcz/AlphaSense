"""Korekta świec o splity i dywidendy (plan krok 45).

Liczby policzone ręcznie, bez bazy — `candles.build_series` jest funkcją
czystą (CLAUDE.md §8: „logika obliczeniowa — testy jednostkowe na znanych
liczbach, bez mocków bazy").
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.modules.marketdata.candles import build_series
from app.modules.marketdata.models import Price


def _price(
    *,
    day: int,
    open_: str | None = "100",
    high: str | None = "110",
    low: str | None = "90",
    close: str | None = "100",
    close_adj: str = "100",
    volume: int | None = 1000,
) -> Price:
    return Price(
        asset_id=None,
        date=date(2026, 1, day),
        open=Decimal(open_) if open_ is not None else None,
        high=Decimal(high) if high is not None else None,
        low=Decimal(low) if low is not None else None,
        close=Decimal(close) if close is not None else None,
        close_adj=Decimal(close_adj),
        volume=volume,
    )


def test_seria_bez_korekt_zostaje_nietknieta() -> None:
    """Stooq/Finnhub/Binance wpisują `close_adj := close`, więc współczynnik
    wynosi dokładnie 1 — świeca ma wyjść identyczna jak surowe OHLC."""
    series = build_series([_price(day=2)])

    candle = series.candles[0]
    assert (candle.open, candle.high, candle.low, candle.close) == (
        Decimal("100.00000000"),
        Decimal("110.00000000"),
        Decimal("90.00000000"),
        Decimal("100.00000000"),
    )
    assert series.skipped == 0


def test_split_2_do_1_skaluje_cala_swiece_tym_samym_wspolczynnikiem() -> None:
    """Dzień sprzed splitu 2:1: `close=100`, `close_adj=50`, więc
    współczynnik to 0.5 i CAŁA świeca schodzi o połowę.

    Gdyby skalować samo zamknięcie, knot 110 wisiałby ponad dwukrotnie
    wyżej niż korpus — dokładnie ten obraz, którego zakazuje CLAUDE.md #4.
    """
    series = build_series([_price(day=2, close_adj="50")])

    candle = series.candles[0]
    assert candle.open == Decimal("50.00000000")
    assert candle.high == Decimal("55.00000000")
    assert candle.low == Decimal("45.00000000")
    assert candle.close == Decimal("50.00000000")
    # Kształt świecy (proporcje) zostaje nietknięty.
    assert (candle.high - candle.low) / (candle.close - candle.low) == Decimal("2")


def test_zamkniecie_bierzemy_wprost_z_close_adj() -> None:
    """`close * (close_adj/close)` i `close_adj` to matematycznie to samo,
    ale pierwsze zostawia błąd zaokrąglenia. Zamknięcie musi zgadzać się
    co do grosza z wykresem wartości portfela i z wyceną pozycji."""
    series = build_series([_price(day=2, close="3", close_adj="1")])

    assert series.candles[0].close == Decimal("1.00000000")


def test_wolumen_przechodzi_bez_skalowania() -> None:
    """`volume` to sztuki, nie cena — skalowanie go współczynnikiem cenowym
    byłoby osobną decyzją, nie efektem ubocznym korekty cen."""
    series = build_series([_price(day=2, close_adj="50", volume=1000)])

    assert series.candles[0].volume == 1000


def test_niekompletny_wiersz_wypada_z_serii_i_jest_policzony() -> None:
    """Dziura w danych ma być widoczna jako liczba, nie domalowana świecą —
    wykres z dziurą wygląda identycznie jak kompletny (CLAUDE.md #3.15)."""
    series = build_series(
        [
            _price(day=2),
            _price(day=3, high=None),
            _price(day=4, open_=None, high=None, low=None, close=None),
            _price(day=5),
        ]
    )

    assert [c.date.day for c in series.candles] == [2, 5]
    assert series.skipped == 2


def test_zerowe_zamkniecie_nie_wywala_dzieleniem() -> None:
    """`close = 0` to artefakt danych, nie cena — brak współczynnika,
    więc wiersz wypada, zamiast przewrócić całą serię."""
    series = build_series([_price(day=2, close="0"), _price(day=3, close="-5")])

    assert series.candles == []
    assert series.skipped == 2


def test_pusta_seria_to_pusta_seria_a_nie_wyjatek() -> None:
    series = build_series([])

    assert series.candles == []
    assert series.skipped == 0
