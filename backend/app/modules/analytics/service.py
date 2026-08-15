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

Krok 30 (ranking rynków, `GET /portfolios/{portfolio_id}/markets`,
ADR-102), decyzje nieprecyzowane wprost przez skill/kontrakt:

- Grupowanie po `asset.market_code` wprost (nie przez `_bucket_key`/
  `by="market"`): `market_code` jest kolumną `NOT NULL` (`marketdata/
  models.py`), więc koszyk „nieznane" fizycznie nie może wystąpić —
  `_bucket_key`/`_distribute_weights` są reużyte tam, gdzie faktycznie się
  zgadzają (kwantyzacja wag do sumy `1`), nie tam, gdzie dodałyby martwą
  gałąź kodu.
- Rynek z niezerową wagą, ale bez `index_asset_id` → `index=None` w
  odpowiedzi (skill: „pokaż samą wagę, bez pustego wykresu").
- Rynek **z** `index_asset_id`, ale bez jeszcze żadnego wiersza `prices`
  (np. świeżo dodany rynek do słownika, worker EOD jeszcze nie zaciągnął
  danych) → traktowany identycznie jak brak indeksu, `index=None` — to nie
  błąd (CLAUDE.md, zasada Redisa uogólniona na dane rynkowe: „brak danych,
  nie błąd"), tylko że tu dotyczy chwilowego braku notowań, nie samego
  Redisa.
- Zmiana d/d indeksu (`change_1d`) liczona wprost z dwóch najnowszych
  wierszy `prices` (nie ze snapshotów jak `portfolio_service._change`) —
  `None`, gdy jest tylko jedno notowanie w historii (nic do porównania) albo
  starsze `close_adj == 0` (matematycznie niemożliwe wobec `CHECK
  close_adj > 0`, ale zabezpieczone obronnie tak samo jak
  `portfolio_service._change` zabezpiecza dzielenie przez `0`).
- `series_30d` to do 30 **ostatnich dostępnych** wierszy `prices` (nie 30
  dni kalendarzowych) — spójne z tym, jak `close_adj`/`fx_pln` wszędzie
  indziej w silniku wyceny cofają się do najnowszego dostępnego notowania,
  a nie żądają dokładnej daty kalendarzowej.

Krok 31 (cache Redis, CLAUDE.md #3.7): `allocation`/`concentration`/
`market_ranking` są dokładnie te trzy funkcje orkiestrujące I/O owinięte
cache'em — każde wywołanie liczy najpierw `_eod_marker` (tani, osobny od
`current_value`) i klucz (`core.cache.cache_key`), próbuje odczytać z
Redisa, na trafienie zwraca zdeserializowany wynik bez dotykania
`portfolio_service.current_value` (ten kosztowny per-pozycja silnik wyceny
to właśnie to, co cache ma omijać), na pudło liczy normalnie i zapisuje.

Decyzje nieprecyzowane wprost przez zadanie:

- `eod_marker` = `MAX(prices.date)` **tylko** dla `asset_id` faktycznie
  trzymanych w tym portfelu (`marketdata_repository.
  get_latest_price_date_for_assets`), NIE `portfolio_service.today()` ani
  najnowszy `IngestionRun` per rynek. Uzasadnienie: `today()` zmienia się o
  północy niezależnie od tego, czy worker EOD faktycznie coś zaciągnął (dałby
  cache miss każdego dnia nawet bez nowych danych, ale też fałszywe trafienie
  cały dzień, zanim worker zdąży dociągnąć dane wieczorem — token nie odróżnia
  „już są nowe dane” od „jeszcze nie"). `IngestionRun` per `market_code`
  wymagałby JOIN-a przez rynek i przejmowania się rynkami spoza portfela.
  `MAX(date)` na faktycznie trzymanych aktywach odpowiada wprost na pytanie
  „czy dla TEGO portfela przyszło coś nowego" i nie wymaga dodatkowej tabeli.
  Portfel bez pozycji / bez żadnej ceny → marker deterministyczny `"none"`
  (nigdy crash pustym `MAX()`).
- Dla `market_ranking` ten sam `eod_marker` (z aktywów trzymanych, nie z
  indeksów rynków) jest wystarczający w praktyce: worker EOD ingestuje w
  jednym przebiegu **wszystkie** aktywne aktywa danego `market_code`,
  włącznie z aktywem indeksu referencyjnego tego rynku (`marketdata.
  repository.list_active_assets`) — jeśli portfel trzyma choć jedną pozycję
  na danym rynku, data jej najnowszej ceny pokrywa się z datą najnowszej ceny
  indeksu tego rynku. Rynek bez żadnej trzymanej pozycji nie wpływa na
  `eod_marker` w ogóle, ale też nie pojawia się w rankingu (`market_ranking`
  grupuje tylko po rynkach obecnych w wycenionych pozycjach) — spójne.
- TTL = 6 godzin (`_CACHE_TTL_SECONDS`) — dane EOD nie zmieniają się
  śróddziennie, a klucz i tak jest wersjonowany (zmiana `holdings_version`/
  `eod_marker` daje nowy klucz, „nie ma inwalidacji", skill `fastapi-modul`);
  TTL istnieje wyłącznie, żeby Redis nie puchł starymi kluczami po dniach,
  gdy portfel/dane już się zmieniły. 6h jest krótsze niż typowy odstęp
  między przebiegami EOD (raz dziennie), więc w najgorszym razie dokłada
  jedno dodatkowe przeliczenie w ciągu dnia, nie realne opóźnienie danych.
- `GET /markets/{code}/index` (marketdata, publiczna, bez `portfolio_id`)
  ŚWIADOMIE nie jest cache'owana w tym kroku — poza zakresem zadania kroku
  31 (dotyczy portfela per-user). Propozycja do rozważenia osobno: mogłaby
  używać klucza `f"market_index:{code}:{range}:{eod_marker_rynku}"` (marker
  liczony inaczej — z `IngestionRun`/`MAX(prices.date)` per rynek, nie per
  portfel), ale to nowa decyzja projektowa, nie robię jej milcząco.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

# `date_`, bo pole `date: date` w klasach niżej PRZESŁANIA nazwę typu
# w ciele klasy — kolejne adnotacje (`as_of`) widziałyby wtedy pole, nie typ.
from datetime import date as date_
from decimal import ROUND_HALF_UP, Decimal
from typing import Any
from uuid import UUID

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import cache_key, get_cached_json, set_cached_json
from app.modules.analytics.benchmark import Quote, benchmark_index
from app.modules.analytics.returns import IndexPoint, ValuationPoint, chain_index, period_return
from app.modules.marketdata import repository as marketdata_repository
from app.modules.marketdata.models import Asset, Price
from app.modules.portfolio import repository as portfolio_repository
from app.modules.portfolio import service as portfolio_service
from app.modules.portfolio.models import Portfolio
from app.modules.portfolio.service import ValuedHolding

# Liczba punktów mini-serii w rankingu rynków (`GET /portfolios/{id}/markets`)
# — skill `analityka-struktury`: „mini-seria 30 dni".
_INDEX_SERIES_DAYS = 30

# Ta sama precyzja co `portfolio/service.py` (`_MONEY_QUANT`/`_PCT_QUANT`) —
# stałe lokalne, nie import prywatnych (podkreślnikowych) nazw z innego
# modułu (skill `fastapi-modul`: moduły nie sięgają sobie do prywatnych
# szczegółów implementacji), ale wartościowo identyczne, żeby zaokrąglenia
# w całym API były spójne.
_MONEY_QUANT = Decimal("0.00000001")  # 8 miejsc — precyzja NUMERIC(20,8)
_PCT_QUANT = Decimal("0.0001")  # 4 miejsca — ułamek (waga/HHI), nie kwota PLN

# Krok 40: zwrot DZIENNY dostaje 6 miejsc, nie 4. Przy `_PCT_QUANT` ruch
# o 3 punkty bazowe (0,0003) traciłby jedną cyfrę znaczącą, a takich dni jest
# na wykresie większość — seria spłaszczyłaby się schodkowo. Indeks
# łańcuchowy ma bazę 100, więc 4 miejsca to tam 1e-6 względnie: wystarczy.
_RETURN_QUANT = Decimal("0.000001")
_INDEX_QUANT = Decimal("0.0001")

# Krok 31 (cache Redis, CLAUDE.md #3.7) — patrz docstring modułu, sekcja
# „Krok 31", dla uzasadnienia markera i TTL.
logger = structlog.get_logger(__name__)

_EOD_MARKER_NONE = "none"
_CACHE_TTL_SECONDS = 6 * 60 * 60  # 6h

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


def _quantize_return(value: Decimal) -> Decimal:
    return value.quantize(_RETURN_QUANT, rounding=ROUND_HALF_UP)


def _quantize_index(value: Decimal) -> Decimal:
    return value.quantize(_INDEX_QUANT, rounding=ROUND_HALF_UP)


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


@dataclass(frozen=True, slots=True)
class IndexChange:
    """Zmiana d/d indeksu referencyjnego, liczona z dwóch najnowszych
    wierszy `prices` — nie mylić z `portfolio_service.Change` (ten liczony
    ze snapshotów `portfolio_valuations`, patrz docstring modułu)."""

    abs: Decimal
    pct: Decimal


@dataclass(frozen=True, slots=True)
class MarketIndexSnapshot:
    """Indeks referencyjny jednego rynku w rankingu — `series_30d` to do
    30 ostatnich dostępnych wierszy `Price`, rosnąco po dacie."""

    asset_id: UUID
    symbol: str
    value: Decimal
    change_1d: IndexChange | None
    as_of: date
    series_30d: list[Price]


@dataclass(frozen=True, slots=True)
class MarketRankingItem:
    """Jeden wiersz rankingu rynków — `index=None`, gdy rynek nie ma
    `index_asset_id` albo nie ma jeszcze żadnego notowania (patrz decyzje
    modułu)."""

    market_code: str
    market_name: str
    weight: Decimal
    index: MarketIndexSnapshot | None


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


def market_weights_from_valued(valued: list[ValuedHolding]) -> dict[str, Decimal]:
    """Waga (0..1, skwantyzowana do sumy dokładnie `1`) każdego
    `asset.market_code` obecnego w pozycjach już wycenionych `valued` —
    funkcja czysta, bez I/O (testowana w `tests/unit/test_analytics.py` bez
    bazy, tak jak `allocation_from_valued`).

    Grupuje wprost po `asset.market_code` (kolumna `NOT NULL`,
    `marketdata/models.py`), nie przez `_bucket_key(..., by="market")` —
    ten koszyk fizycznie nigdy nie trafia do gałęzi „nieznane", więc
    reużywamy tylko to, co faktycznie pasuje: `_distribute_weights`
    (kwantyzacja do sumy dokładnie `1`, rozliczenie zaokrągleń na
    największym koszyku).

    Pozycje bez wyceny (`value_pln is None`) wykluczone z mianownika, tak
    jak w `allocation_from_valued`. Pusty słownik dla portfela pustego /
    bez wycenionych pozycji / sumy `0` — brzegowy przypadek, nie wyjątek.
    """
    included = [vh for vh in valued if vh.value_pln is not None]
    if not included:
        return {}

    raw_totals: dict[str, Decimal] = {}
    for vh in included:
        assert vh.value_pln is not None  # zawężenie typu dla mypy, już odfiltrowane wyżej
        code = vh.asset.market_code
        raw_totals[code] = raw_totals.get(code, Decimal("0")) + vh.value_pln

    total = sum(raw_totals.values(), Decimal("0"))
    if total <= 0:
        return {}

    raw_weights = {k: v / total for k, v in raw_totals.items()}
    return _distribute_weights(raw_weights)


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


async def _eod_marker(db: AsyncSession, portfolio: Portfolio) -> str:
    """Segment „data EOD" klucza cache — patrz docstring modułu, sekcja
    „Krok 31", dla uzasadnienia wyboru `MAX(prices.date)` po aktywach
    faktycznie trzymanych w portfelu (nie `today()`, nie `IngestionRun`).

    Deterministyczny `"none"` dla portfela bez pozycji / bez jeszcze
    żadnej zapisanej ceny — nigdy wyjątek na pustym wyniku."""
    asset_ids = await portfolio_service.list_holding_asset_ids(db, portfolio)
    if not asset_ids:
        return _EOD_MARKER_NONE
    latest = await marketdata_repository.get_latest_price_date_for_assets(db, asset_ids)
    return latest.isoformat() if latest is not None else _EOD_MARKER_NONE


def _allocation_to_json(result: Allocation) -> str:
    return json.dumps(
        {
            "by": result.by,
            "as_of": result.as_of.isoformat(),
            "approximate": result.approximate,
            "buckets": [
                {"key": b.key, "value_pln": str(b.value_pln), "weight": str(b.weight)}
                for b in result.buckets
            ],
        }
    )


def _allocation_from_json(raw: str) -> Allocation:
    data = json.loads(raw)
    return Allocation(
        by=data["by"],
        as_of=date.fromisoformat(data["as_of"]),
        approximate=data["approximate"],
        buckets=[
            AllocationBucket(
                key=b["key"], value_pln=Decimal(b["value_pln"]), weight=Decimal(b["weight"])
            )
            for b in data["buckets"]
        ],
    )


async def allocation(db: AsyncSession, portfolio: Portfolio, *, by: str) -> Allocation:
    """`GET /portfolios/{portfolio_id}/allocation?by=` — orkiestracja I/O:
    wycenia portfel na „dziś" (`portfolio_service.current_value`), potem
    deleguje grupowanie do `allocation_from_valued` (czysta, testowana bez
    bazy). Owinięte cache'em Redis (plan krok 31, CLAUDE.md #3.7, docstring
    modułu „Krok 31") — `by` jest osobnym segmentem klucza, bo każdy wymiar
    ma inny wynik dla tego samego portfela/dnia."""
    key = cache_key(
        "allocation", portfolio.id, portfolio.holdings_version, await _eod_marker(db, portfolio), by
    )
    cached = await get_cached_json(key)
    if cached is not None:
        return _allocation_from_json(cached)

    d = portfolio_service.today()
    value = await portfolio_service.current_value(db, portfolio, d)
    result = allocation_from_valued(value.holdings, by=by, as_of=d)

    await set_cached_json(key, _allocation_to_json(result), ttl_seconds=_CACHE_TTL_SECONDS)
    return result


def _concentration_to_json(result: Concentration) -> str:
    return json.dumps(
        {
            "top5_share": str(result.top5_share),
            "count": result.count,
            "hhi": str(result.hhi),
            "interpretation": result.interpretation,
        }
    )


def _concentration_from_json(raw: str) -> Concentration:
    data = json.loads(raw)
    return Concentration(
        top5_share=Decimal(data["top5_share"]),
        count=data["count"],
        hhi=Decimal(data["hhi"]),
        interpretation=data["interpretation"],
    )


async def concentration(db: AsyncSession, portfolio: Portfolio) -> Concentration:
    """`GET /portfolios/{portfolio_id}/concentration` — orkiestracja I/O,
    patrz `allocation` wyżej. Owinięte cache'em Redis tak samo (krok 31)."""
    key = cache_key(
        "concentration", portfolio.id, portfolio.holdings_version, await _eod_marker(db, portfolio)
    )
    cached = await get_cached_json(key)
    if cached is not None:
        return _concentration_from_json(cached)

    d = portfolio_service.today()
    value = await portfolio_service.current_value(db, portfolio, d)
    result = concentration_from_valued(value.holdings)

    await set_cached_json(key, _concentration_to_json(result), ttl_seconds=_CACHE_TTL_SECONDS)
    return result


def _index_change(current: Decimal, previous: Decimal) -> IndexChange | None:
    """`None`, gdy nie ma z czym porównać (`previous <= 0` — matematycznie
    niemożliwe wobec `CHECK close_adj > 0` w `Price`, ale zabezpieczone
    obronnie tak samo jak `portfolio_service._change`)."""
    if previous <= 0:
        return None
    delta = current - previous
    return IndexChange(abs=_quantize_money(delta), pct=_quantize_pct(delta / previous))


async def _index_snapshot(db: AsyncSession, index_asset_id: UUID) -> MarketIndexSnapshot | None:
    """Wartość/zmiana d/d/mini-seria indeksu referencyjnego jednego rynku —
    `None` gdy w `prices` nie ma jeszcze żadnego notowania (rynek świeżo w
    słowniku, worker EOD jeszcze nie zaciągnął danych — patrz decyzje
    modułu) albo gdy samo `index_asset_id` wskazuje na nieistniejące
    aktywo (złamany FK — asercja obronna, degradujemy do `None` zamiast
    wywalać cały ranking, bo to pojedynczy wiersz odpowiedzi, nie cała
    odpowiedź)."""
    asset = await marketdata_repository.get_asset(db, index_asset_id)
    if asset is None:
        return None

    prices_desc = await marketdata_repository.get_latest_prices(
        db, index_asset_id, limit=_INDEX_SERIES_DAYS
    )
    if not prices_desc:
        return None

    latest = prices_desc[0]
    change = (
        _index_change(latest.close_adj, prices_desc[1].close_adj) if len(prices_desc) >= 2 else None
    )

    return MarketIndexSnapshot(
        asset_id=asset.id,
        symbol=asset.symbol,
        value=_quantize_money(latest.close_adj),
        change_1d=change,
        as_of=latest.date,
        series_30d=list(reversed(prices_desc)),  # najnowsze na końcu — rosnąco po dacie
    )


def _market_index_to_dict(idx: MarketIndexSnapshot | None) -> dict[str, Any] | None:
    if idx is None:
        return None
    return {
        "asset_id": str(idx.asset_id),
        "symbol": idx.symbol,
        "value": str(idx.value),
        "change_1d": (
            {"abs": str(idx.change_1d.abs), "pct": str(idx.change_1d.pct)}
            if idx.change_1d is not None
            else None
        ),
        "as_of": idx.as_of.isoformat(),
        "series_30d": [
            {"date": p.date.isoformat(), "close_adj": str(p.close_adj)} for p in idx.series_30d
        ],
    }


def _market_index_from_dict(data: dict[str, Any] | None) -> MarketIndexSnapshot | None:
    if data is None:
        return None
    change = data["change_1d"]
    series_30d: list[dict[str, Any]] = data["series_30d"]
    return MarketIndexSnapshot(
        asset_id=UUID(str(data["asset_id"])),
        symbol=str(data["symbol"]),
        value=Decimal(str(data["value"])),
        change_1d=(
            IndexChange(abs=Decimal(str(change["abs"])), pct=Decimal(str(change["pct"])))
            if change is not None
            else None
        ),
        as_of=date.fromisoformat(str(data["as_of"])),
        series_30d=[
            # Instancja `Price` transientna (nigdy dodana do sesji) — tylko
            # `date`/`close_adj` są czytane przez `routes.py` z `series_30d`,
            # reszta kolumn (`asset_id`, `close`, ...) zostaje `None`, co nie
            # ma znaczenia dla żadnego konsumenta tego obiektu.
            Price(date=date.fromisoformat(str(p["date"])), close_adj=Decimal(str(p["close_adj"])))
            for p in series_30d
        ],
    )


def _market_ranking_to_json(items: list[MarketRankingItem]) -> str:
    return json.dumps(
        [
            {
                "market_code": item.market_code,
                "market_name": item.market_name,
                "weight": str(item.weight),
                "index": _market_index_to_dict(item.index),
            }
            for item in items
        ]
    )


def _market_ranking_from_json(raw: str) -> list[MarketRankingItem]:
    items: list[dict[str, Any]] = json.loads(raw)
    return [
        MarketRankingItem(
            market_code=str(item["market_code"]),
            market_name=str(item["market_name"]),
            weight=Decimal(str(item["weight"])),
            index=_market_index_from_dict(item["index"]),
        )
        for item in items
    ]


async def market_ranking(db: AsyncSession, portfolio: Portfolio) -> list[MarketRankingItem]:
    """`GET /portfolios/{portfolio_id}/markets` — ranking rynków wg wagi w
    wartości wycenionego portfela (krok 30, ADR-102): wycenia portfel na
    „dziś", grupuje po rynku (`market_weights_from_valued`, czysta),
    dociąga `Market`/indeks referencyjny per rynek obecny w wyniku (jedno
    zapytanie `list_markets_by_codes`, nie N+1 dla samego `Market`),
    sortuje malejąco po wadze (skill: „sortowanie malejąco po wadze").
    Owinięte cache'em Redis (krok 31) — patrz docstring modułu, sekcja
    „Krok 31", dla uzasadnienia, dlaczego ten sam `eod_marker` (z aktywów
    trzymanych w portfelu) wystarcza mimo że tu liczy się też świeżość
    indeksów rynków."""
    key = cache_key(
        "markets", portfolio.id, portfolio.holdings_version, await _eod_marker(db, portfolio)
    )
    cached = await get_cached_json(key)
    if cached is not None:
        return _market_ranking_from_json(cached)

    d = portfolio_service.today()
    value = await portfolio_service.current_value(db, portfolio, d)
    weights = market_weights_from_valued(value.holdings)
    if not weights:
        # Pusty wynik też trafia do cache (spójnie z `allocation`/
        # `concentration`, które cache'ują swoje brzegowe `buckets: []`/
        # `count: 0` tak samo jak wynik niepusty) — portfel bez pozycji
        # inaczej zawsze mijałby cache.
        await set_cached_json(key, _market_ranking_to_json([]), ttl_seconds=_CACHE_TTL_SECONDS)
        return []

    markets = await marketdata_repository.list_markets_by_codes(db, list(weights))
    markets_by_code = {market.code: market for market in markets}

    items: list[MarketRankingItem] = []
    for code, weight in weights.items():
        market = markets_by_code.get(code)
        if market is None:
            # `assets.market_code` ma FK do `markets.code` (marketdata/
            # models.py) — brak wpisu tutaj oznaczałby złamany FK, nie
            # ścieżkę biznesową (ten sam wzorzec obronny co
            # `_require_portfolio` w `portfolio/service.py`).
            raise RuntimeError(
                f"Rynek {code!r} nie istnieje w markets mimo FK z assets.market_code"
            )
        index_snapshot = (
            await _index_snapshot(db, market.index_asset_id)
            if market.index_asset_id is not None
            else None
        )
        items.append(
            MarketRankingItem(
                market_code=code, market_name=market.name, weight=weight, index=index_snapshot
            )
        )

    items.sort(key=lambda item: item.weight, reverse=True)

    await set_cached_json(key, _market_ranking_to_json(items), ttl_seconds=_CACHE_TTL_SECONDS)
    return items


# --- wyniki portfela (plan krok 40, etap 8) --------------------------------


@dataclass(frozen=True, slots=True)
class PerformancePoint:
    """Punkt serii wyników. `ret=None` — zwrotu za ten dzień NIE ZNAMY
    (pierwszy punkt albo zerwane ogniwo), co jest czym innym niż `0`."""

    date: date
    value_pln: Decimal
    ret: Decimal | None
    index: Decimal


@dataclass(frozen=True, slots=True)
class Performance:
    """Wynik `GET /portfolios/{id}/performance?range=`.

    `links` i `skipped_*` nie są diagnostyką dla programisty, tylko częścią
    odpowiedzi na pytanie „ile ten zwrot znaczy": ta sama liczba policzona
    z 250 ogniw i z 40 wygląda identycznie, a znaczy co innego (decyzja 6
    planu etapu 8). UI ma z czego zbudować „za mało danych" bez zgadywania.
    """

    range: str
    period_return: Decimal | None
    first_date: date | None
    last_date: date | None
    links: int
    skipped_composition_change: int
    skipped_zero_base: int
    points: list[PerformancePoint]
    benchmark: BenchmarkSeries | None


def _performance_to_json(result: Performance) -> str:
    return json.dumps(
        {
            "range": result.range,
            "period_return": None if result.period_return is None else str(result.period_return),
            "first_date": None if result.first_date is None else result.first_date.isoformat(),
            "last_date": None if result.last_date is None else result.last_date.isoformat(),
            "links": result.links,
            "skipped_composition_change": result.skipped_composition_change,
            "skipped_zero_base": result.skipped_zero_base,
            "points": [
                {
                    "date": p.date.isoformat(),
                    "value_pln": str(p.value_pln),
                    "ret": None if p.ret is None else str(p.ret),
                    "index": str(p.index),
                }
                for p in result.points
            ],
            "benchmark": _benchmark_to_json(result.benchmark),
        }
    )


def _performance_from_json(raw: str) -> Performance:
    data = json.loads(raw)
    return Performance(
        range=data["range"],
        period_return=(None if data["period_return"] is None else Decimal(data["period_return"])),
        first_date=(None if data["first_date"] is None else date.fromisoformat(data["first_date"])),
        last_date=(None if data["last_date"] is None else date.fromisoformat(data["last_date"])),
        links=data["links"],
        skipped_composition_change=data["skipped_composition_change"],
        skipped_zero_base=data["skipped_zero_base"],
        points=[
            PerformancePoint(
                date=date.fromisoformat(p["date"]),
                value_pln=Decimal(p["value_pln"]),
                ret=None if p["ret"] is None else Decimal(p["ret"]),
                index=Decimal(p["index"]),
            )
            for p in data["points"]
        ],
        benchmark=_benchmark_from_json(data["benchmark"]),
    )


async def performance(
    db: AsyncSession, portfolio: Portfolio, *, range_: str, benchmark: str | None = None
) -> Performance:
    """`GET /portfolios/{portfolio_id}/performance?range=` — orkiestracja I/O
    wokół czystego `analytics.returns` (plan krok 40, ADR-101).

    Marker cache to `valuations_marker`, NIE `_eod_marker`: seria bierze się
    ze snapshotów, nie z cen, a snapshoty potrafią przybyć wstecz
    (`seed-history`) — patrz docstring `portfolio.repository.valuations_marker`.
    `holdings_version` zostaje w kluczu mimo to: zmiana pozycji nie zmienia
    historii wycen, ale zmienia dzisiejszy snapshot już przy najbliższym
    przebiegu EOD, a wtedy i tak potrzebny jest nowy klucz.

    `period_return=None` (nie `0`) dla serii bez ani jednego ogniwa: portfel
    założony wczoraj nie ma zwrotu równego zeru — on go po prostu nie ma,
    i UI musi móc te przypadki rozróżnić (CLAUDE.md #3.15).
    """
    spec = BENCHMARKS[benchmark] if benchmark is not None else None
    # Aktywo benchmarku wyszukane RAZ i podane obu wołającym: marker potrzebuje
    # go do policzenia świeżości, a seria do notowań i waluty.
    benchmark_asset = (
        await marketdata_repository.get_asset_by_symbol(db, spec.symbol)
        if spec is not None
        else None
    )
    key = cache_key(
        "performance",
        portfolio.id,
        portfolio.holdings_version,
        await portfolio_repository.valuations_marker(db, portfolio.id),
        range_,
        # Benchmark ma WŁASNY segment świeżości: jego notowania przychodzą
        # z ingestii rynkowej, nie ze snapshotów portfela, więc
        # `valuations_marker` nie drgnie, gdy dojdzie nowe notowanie
        # `^GSPC`. Bez tego wykres z benchmarkiem zamarzałby na TTL.
        spec.key if spec is not None else "none",
        await _benchmark_marker(db, spec, benchmark_asset),
    )
    cached = await get_cached_json(key)
    if cached is not None:
        return _performance_from_json(cached)

    valuations = await portfolio_repository.list_valuations(
        db, portfolio.id, range_=range_, today=portfolio_service.today()
    )
    points = [
        ValuationPoint(date=v.date, value_pln=v.value_pln, composition_change=v.composition_change)
        for v in valuations
    ]

    total, series = period_return(points)
    index = chain_index(points)

    result = Performance(
        range=range_,
        period_return=_quantize_pct(total) if series.links else None,
        first_date=points[0].date if points else None,
        last_date=points[-1].date if points else None,
        links=series.links,
        skipped_composition_change=series.skipped_composition_change,
        skipped_zero_base=series.skipped_zero_base,
        points=[
            PerformancePoint(
                date=p.date,
                value_pln=_quantize_money(p.value_pln),
                ret=None if p.ret is None else _quantize_return(p.ret),
                index=_quantize_index(p.index),
            )
            for p in index
        ],
        benchmark=(
            await _benchmark_series(db, spec, benchmark_asset, index) if spec is not None else None
        ),
    )

    await set_cached_json(key, _performance_to_json(result), ttl_seconds=_CACHE_TTL_SECONDS)
    return result


# --- benchmark (plan krok 42, etap 8) --------------------------------------


@dataclass(frozen=True, slots=True)
class BenchmarkSpec:
    """Definicja jednego benchmarku: co użytkownik wybiera (`key`) vs czym to
    jest faktycznie liczone (`symbol`).

    Rozdzielone, bo dla GPW to NIE jest to samo. WIG20 nie ma dziś żadnego
    darmowego źródła historii (Stooq oddaje stronę anty-bot, yfinance jeden
    punkt — diagnoza w kroku zerowym etapu 8), więc decyzją 8 planu
    benchmarkiem GPW jest ETF `ETFBW20TR`. Użytkownik nadal wybiera „WIG20",
    bo o to pyta, ale odpowiedź musi powiedzieć, czym to policzono
    (CLAUDE.md #3.15 — przybliżenia oznaczamy).
    """

    key: str
    symbol: str
    label: str
    approximate: bool
    note: str | None


BENCHMARKS: dict[str, BenchmarkSpec] = {
    "WIG20": BenchmarkSpec(
        key="WIG20",
        symbol="ETFBW20TR",
        label="WIG20 (przez Beta ETF WIG20TR)",
        approximate=True,
        note=(
            "Liczone z ETF-a Beta WIG20TR, bo sam indeks WIG20 nie ma dostępnego źródła "
            "historii. ETF śledzi WIG20 Total Return (z dywidendami), dochodzi błąd "
            "odwzorowania i opłata za zarządzanie ok. 0,5% rocznie."
        ),
    ),
    "^GSPC": BenchmarkSpec(
        key="^GSPC", symbol="^GSPC", label="S&P 500", approximate=False, note=None
    ),
}


@dataclass(frozen=True, slots=True)
class BenchmarkSeriesPoint:
    date: date
    as_of: date_
    index: Decimal


@dataclass(frozen=True, slots=True)
class BenchmarkSeries:
    """Seria benchmarku obok serii portfela — albo powód, dla którego jej nie
    ma. `unavailable_reason` niepuste ⇒ `points` puste."""

    key: str
    symbol: str
    label: str
    # `None`, gdy serii nie da się policzyć — pusty string udawałby kod waluty
    # spoza dziedziny opisanej w kontrakcie API.
    currency: str | None
    approximate: bool
    note: str | None
    unavailable_reason: str | None
    # Różnica ostatnich punktów obu serii w punktach procentowych (baza 100).
    # Liczona TUTAJ, na `Decimal`, bo trafia do użytkownika (CLAUDE.md §8),
    # a backend jako jedyny ma obie serie w pełnej precyzji. `None`, gdy
    # którejś serii brakuje albo ich ostatnie punkty nie są z tego samego dnia.
    outperformance: Decimal | None
    points: list[BenchmarkSeriesPoint]


def _benchmark_to_json(series: BenchmarkSeries | None) -> Any:
    if series is None:
        return None
    return {
        "key": series.key,
        "symbol": series.symbol,
        "label": series.label,
        "currency": series.currency,
        "approximate": series.approximate,
        "note": series.note,
        "unavailable_reason": series.unavailable_reason,
        "outperformance": None if series.outperformance is None else str(series.outperformance),
        "points": [
            {"date": p.date.isoformat(), "as_of": p.as_of.isoformat(), "index": str(p.index)}
            for p in series.points
        ],
    }


def _benchmark_from_json(raw: Any) -> BenchmarkSeries | None:
    if raw is None:
        return None
    return BenchmarkSeries(
        key=raw["key"],
        symbol=raw["symbol"],
        label=raw["label"],
        currency=raw["currency"],
        approximate=raw["approximate"],
        note=raw["note"],
        unavailable_reason=raw["unavailable_reason"],
        outperformance=(None if raw["outperformance"] is None else Decimal(raw["outperformance"])),
        points=[
            BenchmarkSeriesPoint(
                date=date.fromisoformat(p["date"]),
                as_of=date.fromisoformat(p["as_of"]),
                index=Decimal(p["index"]),
            )
            for p in raw["points"]
        ],
    )


async def _benchmark_marker(
    db: AsyncSession, spec: BenchmarkSpec | None, asset: Asset | None
) -> str:
    """Segment świeżości klucza cache dla serii benchmarku.

    Osobny od `valuations_marker`, bo to dwa niezależne źródła: snapshoty
    portfela przyrastają z joba wyceny, notowania benchmarku z ingestii
    rynkowej. Portfel bez ruchu i świeże notowanie `^GSPC` to sytuacja
    codzienna — na wspólnym markerze wykres stałby do wygaśnięcia TTL.

    Marker składa się z **trzech** części, bo każda łapie inną zmianę:

    - `MAX(prices.date)` — nowe notowanie od najnowszej strony;
    - `COUNT(*)` notowań — historia dopisana **wstecz** przez `make backfill`
      (`price_marker_for_asset` tłumaczy, dlaczego samo maksimum kłamie);
    - `MAX(fx_rates.date)` waluty benchmarku, gdy nie jest nim PLN — nowy
      kurs NBP bez nowego notowania jest stanem codziennym, nie skrajnym.

    `asset` przychodzi z zewnątrz zamiast być wyszukiwany tutaj: `_benchmark_series`
    i tak go potrzebuje, a dwa `get_asset_by_symbol` na jednej ścieżce żądania
    to jedno zapytanie za dużo.
    """
    if spec is None or asset is None:
        return _EOD_MARKER_NONE
    latest, count = await marketdata_repository.price_marker_for_asset(db, asset.id)
    segments = [latest.isoformat() if latest is not None else _EOD_MARKER_NONE, str(count)]
    if asset.currency != "PLN":
        fx_latest = await marketdata_repository.get_latest_fx_rate_date(db, asset.currency)
        segments.append(fx_latest.isoformat() if fx_latest is not None else _EOD_MARKER_NONE)
    return ":".join(segments)


def _outperformance(
    portfolio_points: Sequence[IndexPoint], benchmark_points: Sequence[BenchmarkSeriesPoint]
) -> Decimal | None:
    """O ile punktów procentowych portfel pobił benchmark na końcu okna.

    Obie serie mają bazę 100 w pierwszym wspólnym dniu, więc różnica ostatnich
    wartości **jest** różnicą stóp zwrotu w punktach procentowych — nie trzeba
    niczego dzielić.

    Liczone tutaj, nie we froncie: wynik trafia do użytkownika, a CLAUDE.md §8
    zabrania liczenia takich rzeczy na `float`. Backend jako jedyny ma obie
    serie w `Decimal`.

    **Zgodność ostatnich dat jest sprawdzana, nie zakładana.** Dziś
    `benchmark_index` wyrównuje się do dat portfela, więc warunek jest zawsze
    spełniony — ale funkcja porównująca dwie serie nie ma prawa milcząco
    zakładać, że ktoś ją tak zawoła. Rozjazd daje `None` („nie wiemy"),
    nie liczbę policzoną z dwóch różnych dni.
    """
    if not portfolio_points or not benchmark_points:
        return None
    last_portfolio, last_benchmark = portfolio_points[-1], benchmark_points[-1]
    if last_portfolio.date != last_benchmark.date:
        return None
    return _quantize_index(last_portfolio.index - last_benchmark.index)


def _unavailable(spec: BenchmarkSpec, currency: str | None, reason: str) -> BenchmarkSeries:
    return BenchmarkSeries(
        key=spec.key,
        symbol=spec.symbol,
        label=spec.label,
        currency=currency,
        approximate=spec.approximate,
        note=spec.note,
        unavailable_reason=reason,
        outperformance=None,
        points=[],
    )


async def _benchmark_series(
    db: AsyncSession,
    spec: BenchmarkSpec,
    asset: Asset | None,
    portfolio_points: Sequence[IndexPoint],
) -> BenchmarkSeries:
    """Seria benchmarku wyrównana do `dates` (daty snapshotów portfela).

    Dwa zapytania niezależnie od długości okna (`list_*_with_carry`), całe
    wyrównanie robi czysty `analytics.benchmark`. Każda ścieżka „nie da się"
    kończy się `unavailable_reason` po polsku, nie pustą serią bez wyjaśnienia
    — wykres bez linii i bez powodu wygląda jak awaria (CLAUDE.md #3.15).
    """
    if asset is None:
        # Dwa różne komunikaty do dwóch różnych odbiorców. Użytkownik dostaje
        # zdanie, na które może zareagować (czyli: nic nie może zrobić, ale wie,
        # że to nie jego wina), a instrukcja `make seed` idzie do logów, bo
        # adresatem jest operator instancji. Pierwsza wersja wysyłała
        # użytkownikowi polecenie powłoki, którego nie ma jak wykonać.
        logger.error(
            "benchmark.asset_missing",
            symbol=spec.symbol,
            benchmark=spec.key,
            hint="Brak aktywa benchmarku w słowniku — uruchom `make seed`.",
        )
        return _unavailable(spec, None, f"Porównanie z {spec.label} jest chwilowo niedostępne.")
    dates = [p.date for p in portfolio_points]
    if not dates:
        return _unavailable(spec, asset.currency, "Portfel nie ma jeszcze historii wyceny.")

    start, end = dates[0], dates[-1]
    prices = await marketdata_repository.list_prices_with_carry(db, asset.id, start=start, end=end)
    quotes = [Quote(date=p.date, value=p.close_adj) for p in prices]

    fx_quotes: list[Quote] | None = None
    if asset.currency != "PLN":
        # Decyzja 4 planu etapu 8 — benchmark przeliczany na PLN kursem NBP,
        # tak samo jak wycena portfela (CLAUDE.md #3.5).
        rates = await marketdata_repository.list_fx_rates_with_carry(
            db, asset.currency, start=start, end=end
        )
        fx_quotes = [Quote(date=r.date, value=r.rate_pln) for r in rates]

    points = benchmark_index(dates, quotes, fx_quotes)
    if not points:
        return _unavailable(
            spec,
            asset.currency,
            (
                f"Brak notowań {spec.symbol} na dzień {start.isoformat()} lub wcześniej — "
                "nie ma wspólnego punktu odniesienia dla obu serii."
            ),
        )

    quantized = [
        BenchmarkSeriesPoint(date=p.date, as_of=p.as_of, index=_quantize_index(p.index))
        for p in points
    ]
    return BenchmarkSeries(
        key=spec.key,
        symbol=spec.symbol,
        label=spec.label,
        currency=asset.currency,
        approximate=spec.approximate,
        note=spec.note,
        unavailable_reason=None,
        outperformance=_outperformance(portfolio_points, quantized),
        points=quantized,
    )
