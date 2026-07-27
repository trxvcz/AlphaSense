"""Testy jednostkowe logiki alokacji/koncentracji
(`app.modules.analytics.service`) — wzory skila `analityka-struktury`.

Bez bazy, bez mocków ORM (docs/konwencje.md) — `allocation_from_valued`/
`concentration_from_valued` są funkcjami czystymi (biorą już wycenione
`ValuedHolding`, zero I/O); orkiestracja I/O wokół nich
(`service.allocation`/`service.concentration`, `portfolio_service.
current_value`) jest pokryta testami integracyjnymi w
`tests/integration/test_analytics.py`.

`Asset`/`Holding` instancjonowane bezpośrednio (bez sesji, jak
`app/db/seed.py`/`tests/integration/test_holdings.py`) — wystarczy do
przetestowania logiki grupowania, `id`/`portfolio_id`/`asset_id` nie są tu
potrzebne.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.modules.analytics.service import (
    allocation_from_valued,
    concentration_from_valued,
    market_weights_from_valued,
)
from app.modules.marketdata.models import Asset
from app.modules.portfolio.models import Holding
from app.modules.portfolio.service import ValuedHolding

TODAY = date(2026, 7, 27)


def _asset(
    *,
    asset_class: str = "equity",
    sector: str | None = None,
    country: str | None = None,
    region: str | None = None,
    currency: str = "PLN",
    market_code: str = "GPW",
    symbol: str = "TEST",
) -> Asset:
    return Asset(
        symbol=symbol,
        name=symbol,
        asset_class=asset_class,
        market_code=market_code,
        currency=currency,
        sector=sector,
        country=country,
        region=region,
    )


def _valued(
    *,
    value_pln: Decimal | None,
    asset: Asset,
    quantity: Decimal = Decimal("1"),
) -> ValuedHolding:
    return ValuedHolding(
        holding=Holding(quantity=quantity),
        asset=asset,
        value_pln=value_pln,
        stale=False,
        as_of=TODAY if value_pln is not None else None,
        unrealized_pl=None,
        split_suspected=False,
    )


# ---------------------------------------------------------------------------
# Alokacja
# ---------------------------------------------------------------------------


def test_allocation_weights_sum_to_exactly_one_despite_rounding() -> None:
    """3 koszyki po 1/3 wartości portfela — 0.3333 × 3 = 0.9999, różnica
    zaokrągleń MUSI trafić do jednego koszyka, żeby suma wyszła dokładnie 1
    (skill `analityka-struktury`, test obowiązkowy)."""
    valued = [
        _valued(value_pln=Decimal("100"), asset=_asset(asset_class="equity", symbol="A")),
        _valued(value_pln=Decimal("100"), asset=_asset(asset_class="etf", symbol="B")),
        _valued(value_pln=Decimal("100"), asset=_asset(asset_class="crypto", symbol="C")),
    ]

    result = allocation_from_valued(valued, by="class", as_of=TODAY)

    assert sum(b.weight for b in result.buckets) == Decimal("1")
    assert len(result.buckets) == 3


def test_allocation_uneven_split_sums_to_one() -> None:
    """Podział, który nie dzieli się trywialnie (7/3 portfela vs 2/3) —
    dodatkowy przypadek zaokrągleń nietrywialnych."""
    valued = [
        _valued(value_pln=Decimal("700"), asset=_asset(asset_class="equity", symbol="A")),
        _valued(value_pln=Decimal("300"), asset=_asset(asset_class="etf", symbol="B")),
    ]

    result = allocation_from_valued(valued, by="class", as_of=TODAY)

    assert sum(b.weight for b in result.buckets) == Decimal("1")


def test_allocation_missing_attribute_goes_to_unknown_bucket() -> None:
    """Brak sektora → koszyk `"nieznane"`, pozycja nadal wliczona do sumy
    (skill: „nigdy pominięcie pozycji")."""
    valued = [
        _valued(value_pln=Decimal("50"), asset=_asset(sector="Technologia", symbol="A")),
        _valued(value_pln=Decimal("50"), asset=_asset(sector=None, symbol="B")),
    ]

    result = allocation_from_valued(valued, by="sector", as_of=TODAY)

    keys = {b.key for b in result.buckets}
    assert "nieznane" in keys
    assert sum(b.weight for b in result.buckets) == Decimal("1")
    unknown = next(b for b in result.buckets if b.key == "nieznane")
    assert unknown.weight == Decimal("0.5")


def test_allocation_geo_falls_back_to_region_when_country_missing() -> None:
    """Decyzja: `by=geo` = `country`, a gdy brak — `region` (zamiast od
    razu „nieznane") — patrz docstring `service.py`."""
    valued = [
        _valued(
            value_pln=Decimal("100"),
            asset=_asset(country=None, region="Globalny", symbol="BTC"),
        ),
    ]

    result = allocation_from_valued(valued, by="geo", as_of=TODAY)

    assert len(result.buckets) == 1
    assert result.buckets[0].key == "Globalny"


def test_allocation_excludes_unvalued_positions_from_denominator() -> None:
    """Pozycja bez `value_pln` (brak notowania) nie ma czym wnieść wagi —
    wykluczona z mianownika, nie pokazana jako `0`."""
    valued = [
        _valued(value_pln=Decimal("100"), asset=_asset(asset_class="equity", symbol="A")),
        _valued(value_pln=None, asset=_asset(asset_class="crypto", symbol="B")),
    ]

    result = allocation_from_valued(valued, by="class", as_of=TODAY)

    assert len(result.buckets) == 1
    assert result.buckets[0].weight == Decimal("1")


def test_allocation_empty_portfolio_returns_empty_buckets() -> None:
    result = allocation_from_valued([], by="class", as_of=TODAY)

    assert result.buckets == []
    assert result.approximate is False


def test_allocation_only_unvalued_positions_returns_empty_buckets() -> None:
    """Portfel z pozycjami, ale żadna nie ma wyceny — jak portfel pusty
    z punktu widzenia alokacji (nie ma czego rozbić procentowo)."""
    valued = [_valued(value_pln=None, asset=_asset())]

    result = allocation_from_valued(valued, by="class", as_of=TODAY)

    assert result.buckets == []


def test_allocation_approximate_true_only_for_sector_and_geo_with_etf() -> None:
    """ETF w portfelu → `approximate=true` TYLKO dla `sector`/`geo`; klasa,
    waluta i rynek ETF-a są znane wprost, nie przybliżone."""
    valued = [
        _valued(
            value_pln=Decimal("100"),
            asset=_asset(asset_class="etf", sector="Technologia", country="USA", symbol="QQQ"),
        ),
    ]

    assert allocation_from_valued(valued, by="sector", as_of=TODAY).approximate is True
    assert allocation_from_valued(valued, by="geo", as_of=TODAY).approximate is True
    assert allocation_from_valued(valued, by="class", as_of=TODAY).approximate is False
    assert allocation_from_valued(valued, by="currency", as_of=TODAY).approximate is False
    assert allocation_from_valued(valued, by="market", as_of=TODAY).approximate is False


def test_allocation_without_etf_is_never_approximate() -> None:
    valued = [_valued(value_pln=Decimal("100"), asset=_asset(asset_class="equity", sector="X"))]

    assert allocation_from_valued(valued, by="sector", as_of=TODAY).approximate is False
    assert allocation_from_valued(valued, by="geo", as_of=TODAY).approximate is False


# ---------------------------------------------------------------------------
# Koncentracja / HHI
# ---------------------------------------------------------------------------


def test_concentration_single_position_hhi_is_one() -> None:
    valued = [_valued(value_pln=Decimal("1000"), asset=_asset())]

    result = concentration_from_valued(valued)

    assert result.hhi == Decimal("1")
    assert result.top5_share == Decimal("1")
    assert result.count == 1
    assert result.interpretation == "wysoka"


def test_concentration_ten_equal_positions_hhi_is_point_one() -> None:
    valued = [_valued(value_pln=Decimal("100"), asset=_asset(symbol=f"P{i}")) for i in range(10)]

    result = concentration_from_valued(valued)

    assert result.hhi == Decimal("0.1000")
    assert result.count == 10
    assert result.interpretation == "niska"


def test_concentration_top5_share_sums_five_largest_positions() -> None:
    # 5 pozycji po 100, 5 pozycji po 20 -> suma = 600, top5 = 500/600
    valued = [
        _valued(value_pln=Decimal("100"), asset=_asset(symbol=f"BIG{i}")) for i in range(5)
    ] + [_valued(value_pln=Decimal("20"), asset=_asset(symbol=f"SMALL{i}")) for i in range(5)]

    result = concentration_from_valued(valued)

    # 500/600 = 0.8333... -> zaokrąglone (ROUND_HALF_UP, 4 miejsca) do 0.8333
    assert result.top5_share == Decimal("0.8333")
    assert result.count == 10


def test_concentration_empty_portfolio_is_zero_not_error() -> None:
    result = concentration_from_valued([])

    assert result.top5_share == Decimal("0")
    assert result.count == 0
    assert result.hhi == Decimal("0")
    assert result.interpretation == "niska"


def test_concentration_only_unvalued_positions_is_zero_not_error() -> None:
    valued = [_valued(value_pln=None, asset=_asset())]

    result = concentration_from_valued(valued)

    assert result.count == 0
    assert result.hhi == Decimal("0")


def test_concentration_interpretation_thresholds() -> None:
    # HHI dokładnie na granicach: <0.15 niska, 0.15-0.25 średnia, >0.25 wysoka.
    # 7 pozycji równych -> hhi = 1/7 ≈ 0.142857 -> niska
    seven_equal = [_valued(value_pln=Decimal("1"), asset=_asset(symbol=f"S{i}")) for i in range(7)]
    assert concentration_from_valued(seven_equal).interpretation == "niska"

    # 5 pozycji równych -> hhi = 1/5 = 0.2 -> średnia
    five_equal = [_valued(value_pln=Decimal("1"), asset=_asset(symbol=f"M{i}")) for i in range(5)]
    assert concentration_from_valued(five_equal).interpretation == "średnia"

    # 2 pozycje równe -> hhi = 1/2 = 0.5 -> wysoka
    two_equal = [_valued(value_pln=Decimal("1"), asset=_asset(symbol=f"L{i}")) for i in range(2)]
    assert concentration_from_valued(two_equal).interpretation == "wysoka"


# ---------------------------------------------------------------------------
# Ranking rynków — waga po market_code (krok 30, ADR-102)
# ---------------------------------------------------------------------------


def test_market_weights_sums_to_one_and_groups_by_market_code() -> None:
    valued = [
        _valued(value_pln=Decimal("500"), asset=_asset(market_code="GPW", symbol="A")),
        _valued(value_pln=Decimal("300"), asset=_asset(market_code="GPW", symbol="B")),
        _valued(value_pln=Decimal("200"), asset=_asset(market_code="US", symbol="C")),
    ]

    weights = market_weights_from_valued(valued)

    assert set(weights) == {"GPW", "US"}
    assert sum(weights.values()) == Decimal("1")
    assert weights["GPW"] == Decimal("0.8000")
    assert weights["US"] == Decimal("0.2000")


def test_market_weights_uneven_split_sums_to_one() -> None:
    """Podział nietrywialny (1/3 vs 2/3) — zaokrąglenia MUSZĄ trafić do
    jednego rynku, żeby suma wyszła dokładnie `1` (ta sama zasada co
    `allocation_from_valued`, patrz `_distribute_weights`)."""
    valued = [
        _valued(value_pln=Decimal("100"), asset=_asset(market_code="GPW", symbol="A")),
        _valued(value_pln=Decimal("100"), asset=_asset(market_code="US", symbol="B")),
        _valued(value_pln=Decimal("100"), asset=_asset(market_code="CRYPTO", symbol="C")),
    ]

    weights = market_weights_from_valued(valued)

    assert sum(weights.values()) == Decimal("1")
    assert len(weights) == 3


def test_market_weights_excludes_unvalued_positions_from_denominator() -> None:
    valued = [
        _valued(value_pln=Decimal("100"), asset=_asset(market_code="GPW", symbol="A")),
        _valued(value_pln=None, asset=_asset(market_code="US", symbol="B")),
    ]

    weights = market_weights_from_valued(valued)

    assert weights == {"GPW": Decimal("1")}


def test_market_weights_empty_portfolio_returns_empty_dict() -> None:
    assert market_weights_from_valued([]) == {}


def test_market_weights_only_unvalued_positions_returns_empty_dict() -> None:
    valued = [_valued(value_pln=None, asset=_asset(market_code="GPW"))]

    assert market_weights_from_valued(valued) == {}
