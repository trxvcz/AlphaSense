"""Logika domenowa modułu `analytics`: alokacja wg wymiaru (klasa/sektor/
geografia/waluta/rynek) i koncentracja (HHI) — plan krok 29, etap 6, serce
produktu (CLAUDE.md §1).

Wzory tu opisane są kontraktem skila `analityka-struktury` — NIE odstępuj
bez zapytania:

    alokacja: SUM(value_pln) / SUM(SUM(value_pln)) OVER () AS weight, GROUP BY bucket
    koncentracja: top5_share = suma wag 5 największych POZYCJI (nie koszyków)
                  hhi = Σ wᵢ² po wagach POZYCJI (nie koszyków)

Podział na funkcje czyste (`_bucket_key`, `_distribute_weights`,
`allocation_from_valued`, `concentration_from_valued` — biorą już wycenione
`ValuedHolding`, zero I/O, testowane w `tests/unit/test_analytics.py` bez
bazy) i orkiestrację I/O (`allocation`/`concentration` — wołają
`portfolio_service.current_value`, pokryte w
`tests/integration/test_analytics.py`) — ten sam wzorzec co
`portfolio/service.py` (`value_position` vs `_value_pairs`).

`routes.py` woła wyłącznie funkcje stąd — zero SQL w routingu (skill
`fastapi-modul`).

Decyzje podjęte tutaj, bo kontrakt/skill ich nie precyzowały (raportowane
też w podsumowaniu zadania):

- `by=geo` używa `asset.country`, a gdy ten jest `None` — `asset.region`
  (dwustopniowe „nieznane": kraj > region > koszyk `"nieznane"`). Bardziej
  szczegółowy atrybut (kraj) ma pierwszeństwo, bo jest bardziej użyteczny na
  dashboardzie; region jest sensownym fallbackiem zamiast od razu wrzucać
  pozycję bez kraju (typowe dla indeksów/krypto — patrz `app/db/seed.py`,
  gdzie krypto/złoto mają tylko `region="Globalny"`, bez `country`) do
  koszyka „nieznane”.
- Portfel bez wycenionych pozycji (albo suma wartości wycenionych pozycji
  równa `0`, np. same pozycje o `quantity=0`) traktowany identycznie jak
  portfel pusty — `buckets: []` dla alokacji, `count=0`/`hhi="0"`/
  `top5_share="0"` dla koncentracji. Nie ma nic sensownego do pokazania jako
  proporcja z mianownikiem `0` — brzegowy przypadek, nie wyjątek (zgodnie z
  instrukcją zadania).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.marketdata.models import Asset
from app.modules.portfolio import service as portfolio_service
from app.modules.portfolio.models import Portfolio
from app.modules.portfolio.service import ValuedHolding

# Ta sama precyzja co `portfolio/service.py` (`_MONEY_QUANT`/`_PCT_QUANT`) —
# stałe lokalne, nie import prywatnych (podkreślnikowych) nazw z innego
# modułu (skill `fastapi-modul`: moduły nie sięgają sobie do prywatnych
# szczegółów implementacji), ale wartościowo identyczne, żeby zaokrąglenia
# w całym API były spójne.
_MONEY_QUANT = Decimal("0.00000001")  # 8 miejsc — precyzja NUMERIC(20,8)
_PCT_QUANT = Decimal("0.0001")  # 4 miejsca — ułamek (waga/HHI), nie kwota PLN

_UNKNOWN_BUCKET = "nieznane"

# Wymiary alokacji dopuszczone przez kontrakt (docs/api-kontrakt.md).
ALLOCATION_DIMENSIONS = ("class", "sector", "geo", "currency", "market")

# `by` dla których sektor/geografia ETF-a jest z definicji przybliżeniem
# (skill `analityka-struktury`) — klasa/waluta/rynek ETF-a to fizycznie
# znane, nieprzybliżone atrybuty (ETF jest notowany w konkretnej walucie,
# na konkretnym rynku, i ma jednoznaczną `asset_class="etf"`).
_APPROXIMATE_DIMENSIONS = frozenset({"sector", "geo"})

_ETF_ASSET_CLASS = "etf"


def _quantize_money(value: Decimal) -> Decimal:
    return value.quantize(_MONEY_QUANT, rounding=ROUND_HALF_UP)


def _quantize_pct(value: Decimal) -> Decimal:
    return value.quantize(_PCT_QUANT, rounding=ROUND_HALF_UP)


@dataclass(frozen=True, slots=True)
class AllocationBucket:
    key: str
    value_pln: Decimal
    weight: Decimal


@dataclass(frozen=True, slots=True)
class Allocation:
    by: str
    as_of: date
    approximate: bool
    buckets: list[AllocationBucket]


@dataclass(frozen=True, slots=True)
class Concentration:
    top5_share: Decimal
    count: int
    hhi: Decimal
    interpretation: str


def _bucket_key(asset: Asset, by: str) -> str:
    """Atrybut aktywa użyty do grupowania dla danego wymiaru `by`.

    Brak wartości (`None`, albo pusty string — obronnie, kolumny `class`/
    `currency`/`market` są `NOT NULL` w bazie, ale nie polegamy na tym w
    funkcji czystej) → koszyk `"nieznane"` (skill `analityka-struktury`:
    „Brak atrybutu → koszyk nieznane, nigdy pominięcie pozycji").
    """
    if by == "class":
        value: str | None = asset.asset_class
    elif by == "sector":
        value = asset.sector
    elif by == "geo":
        # Decyzja (patrz docstring modułu): kraj ma pierwszeństwo, region
        # jest fallbackiem, dopiero potem "nieznane".
        value = asset.country or asset.region
    elif by == "currency":
        value = asset.currency
    elif by == "market":
        value = asset.market_code
    else:
        raise ValueError(f"Nieznany wymiar alokacji: {by!r}")
    return value if value else _UNKNOWN_BUCKET


def _distribute_weights(raw_weights: dict[str, Decimal]) -> dict[str, Decimal]:
    """Kwantyzuje wagi (4 miejsca, `ROUND_HALF_UP`) tak, żeby suma wyszła
    dokładnie `1` — skill `analityka-struktury`: „Suma wag = 1 zawsze (test
    obowiązkowy). Zaokrąglenia rozliczaj na największym koszyku."

    Każda pojedyncza kwantyzacja do 4 miejsc gubi/dodaje ułamek grosza;
    zsumowane osobno kwantyzowane wagi prawie nigdy nie dają dokładnie `1`
    (np. 3 koszyki po 1/3 → 0.3333×3 = 0.9999). Różnicę dokładamy do
    koszyka z największą wagą PRZED kwantyzacją — tam korekta jest
    relatywnie najmniej zauważalna. Remis (dwa koszyki o identycznej
    nieskwantyzowanej wadze) rozstrzygamy deterministycznie po nazwie
    klucza (żeby wynik nie zależał od kolejności iteracji słownika).
    """
    if not raw_weights:
        return {}
    quantized = {k: _quantize_pct(v) for k, v in raw_weights.items()}
    diff = Decimal("1") - sum(quantized.values(), Decimal("0"))
    if diff != 0:
        largest_key = max(raw_weights, key=lambda k: (raw_weights[k], k))
        quantized[largest_key] = _quantize_pct(quantized[largest_key] + diff)
    return quantized


def allocation_from_valued(valued: list[ValuedHolding], *, by: str, as_of: date) -> Allocation:
    """Grupuje pozycje już wycenione (`ValuedHolding`) w koszyki `by`.

    Pozycje bez wyceny (`value_pln is None`) są wykluczone z mianownika —
    fizycznie nie mają czym wnieść wagi (tak jak `current_value` już robi
    to dla `total_pln`), ale nadal istnieją jako pozycja portfela (nie
    znikają z `GET /holdings`, tylko z tego rozbicia).
    """
    if by not in ALLOCATION_DIMENSIONS:
        raise ValueError(f"Nieznany wymiar alokacji: {by!r}")

    included = [vh for vh in valued if vh.value_pln is not None]
    if not included:
        return Allocation(by=by, as_of=as_of, approximate=False, buckets=[])

    raw_totals: dict[str, Decimal] = {}
    approximate = False
    check_approximate = by in _APPROXIMATE_DIMENSIONS
    for vh in included:
        assert vh.value_pln is not None  # zawężenie typu dla mypy, już odfiltrowane wyżej
        key = _bucket_key(vh.asset, by)
        raw_totals[key] = raw_totals.get(key, Decimal("0")) + vh.value_pln
        if check_approximate and vh.asset.asset_class == _ETF_ASSET_CLASS:
            approximate = True

    total = sum(raw_totals.values(), Decimal("0"))
    if total <= 0:
        # Brzegowy przypadek: same wycenione pozycje o wartości 0 (np.
        # `quantity=0`) — mianownik `0`, nic sensownego do pokazania jako
        # proporcja (patrz docstring modułu, ta sama decyzja co dla
        # `concentration_from_valued`).
        return Allocation(by=by, as_of=as_of, approximate=False, buckets=[])

    raw_weights = {k: v / total for k, v in raw_totals.items()}
    weights = _distribute_weights(raw_weights)

    buckets = [
        AllocationBucket(key=key, value_pln=_quantize_money(raw_totals[key]), weight=weights[key])
        for key in raw_totals
    ]
    buckets.sort(key=lambda b: b.weight, reverse=True)

    return Allocation(by=by, as_of=as_of, approximate=approximate, buckets=buckets)


def _interpretation(hhi_value: Decimal) -> str:
    """Interpretacja opisowa HHI — jedno miejsce w kodzie (skill
    `analityka-struktury`: „nie rozsiane po UI”)."""
    if hhi_value < Decimal("0.15"):
        return "niska"
    if hhi_value <= Decimal("0.25"):
        return "średnia"
    return "wysoka"


def concentration_from_valued(valued: list[ValuedHolding]) -> Concentration:
    """`top5_share`/`hhi` liczone po WAGACH POZYCJI (nie koszyków, skill
    `analityka-struktury`) — mianownik to suma `value_pln` wycenionych
    pozycji, tak jak w `allocation_from_valued`.
    """
    included_values = [vh.value_pln for vh in valued if vh.value_pln is not None]
    total = sum(included_values, Decimal("0"))
    if total <= 0:
        return Concentration(
            top5_share=Decimal("0"),
            count=0,
            hhi=Decimal("0"),
            interpretation=_interpretation(Decimal("0")),
        )

    weights = sorted((v / total for v in included_values), reverse=True)
    hhi_value = _quantize_pct(sum((w * w for w in weights), Decimal("0")))
    top5_share = _quantize_pct(sum(weights[:5], Decimal("0")))

    return Concentration(
        top5_share=top5_share,
        count=len(weights),
        hhi=hhi_value,
        interpretation=_interpretation(hhi_value),
    )


async def allocation(db: AsyncSession, portfolio: Portfolio, *, by: str) -> Allocation:
    """`GET /portfolios/{portfolio_id}/allocation?by=` — orkiestracja I/O:
    wycenia portfel na „dziś" (`portfolio_service.current_value`), potem
    deleguje grupowanie do `allocation_from_valued` (czysta, testowana bez
    bazy)."""
    d = portfolio_service.today()
    value = await portfolio_service.current_value(db, portfolio, d)
    return allocation_from_valued(value.holdings, by=by, as_of=d)


async def concentration(db: AsyncSession, portfolio: Portfolio) -> Concentration:
    """`GET /portfolios/{portfolio_id}/concentration` — orkiestracja I/O,
    patrz `allocation` wyżej."""
    d = portfolio_service.today()
    value = await portfolio_service.current_value(db, portfolio, d)
    return concentration_from_valued(value.holdings)
