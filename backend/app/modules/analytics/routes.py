"""Routing modułu `analytics` — alokacja, koncentracja (plan krok 29, etap 6)
i ranking rynków (`/portfolios/{id}/markets`, krok 30, ADR-102). Ryzyko i
wyniki (`/risk`, `/performance`) to Faza 2 (plan, krok 41 i dalej).

Zero SQL bezpośrednio tutaj (skill `fastapi-modul`) — każdy handler woła
`service.py`. Autoryzacja zasobowa wyłącznie przez `Depends(get_owned_
portfolio)` (`core/deps.py`, skill `izolacja-danych`) — nigdy goły
`portfolio_id` z path bez weryfikacji właściciela. `GET /markets/{code}/
index` (druga część kroku 30) żyje w `modules/marketdata/routes.py` — dotyczy
wyłącznie danych rynkowych globalnych (bez portfela), publiczna trasa jak
`/assets/search` (patrz raport zadania kroku 30).
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated

from fastapi import APIRouter, Query

from app.core.deps import PortfolioDep
from app.db.session import DbSession
from app.modules.analytics import service
from app.modules.analytics.schemas import (
    AllocationBucketOut,
    AllocationOut,
    BenchmarkOut,
    BenchmarkPointOut,
    BetaOut,
    ConcentrationOut,
    DrawdownOut,
    IndexChangeOut,
    MarketIndexOut,
    MarketRankingItemOut,
    MonthlyReturnOut,
    PerformanceOut,
    PerformancePointOut,
    RiskOut,
    UnderwaterPointOut,
)
from app.modules.marketdata.schemas import PricePointOut
from app.modules.portfolio.routes import ValuationRangeParam

router = APIRouter(tags=["analytics"])


class BenchmarkParam(StrEnum):
    """`?benchmark=` w `GET /performance` (krok 42).

    Wartości są KLUCZAMI z `service.BENCHMARKS`, nie symbolami aktywów:
    użytkownik wybiera „WIG20", a liczone jest to z ETF-a `ETFBW20TR`
    (decyzja 8 planu etapu 8 — WIG20 nie ma dostępnego źródła historii).
    Odpowiedź niesie `symbol`, `approximate` i `note`, więc podmiana jest
    jawna, nie ukryta (CLAUDE.md #3.15).

    Zamknięty enum, nie dowolny symbol: `?benchmark=` z otwartą dziedziną
    byłby obietnicą, że każde aktywo ze słownika ma historię nadającą się
    na benchmark, a nie ma (`WIG20` w bazie dev ma trzy notowania).
    """

    WIG20 = "WIG20"
    SP500 = "^GSPC"


class AllocationDimensionParam(StrEnum):
    """`?by=` w `GET /allocation` — string enum: FastAPI/Pydantic zwraca 422
    na nieznaną wartość zamiast przepuszczać dowolny tekst do
    `service.allocation`/`service._bucket_key` (ten sam wzorzec co
    `ValuationRangeParam` w `modules/portfolio/routes.py`)."""

    CLASS = "class"
    SECTOR = "sector"
    GEO = "geo"
    CURRENCY = "currency"
    MARKET = "market"


@router.get("/portfolios/{portfolio_id}/performance", response_model=PerformanceOut)
async def get_performance(
    portfolio: PortfolioDep,
    db: DbSession,
    range_: Annotated[ValuationRangeParam, Query(alias="range")] = ValuationRangeParam.MAX,
    benchmark: Annotated[BenchmarkParam | None, Query()] = None,
) -> PerformanceOut:
    """Zwrot za okres i seria indeksu łańcuchowego ze snapshotów (krok 40,
    ADR-101). Dni zmiany składu zrywają ogniwo — patrz `analytics.returns`.

    `benchmark` (krok 42) dokłada drugą serię znormalizowaną do 100 w tym
    samym dniu co portfel, przeliczoną na PLN kursem NBP (decyzja 4 planu).

    `range` reużywa `ValuationRangeParam` z `portfolio.routes` zamiast
    definiować drugi enum o tych samych wartościach: obie trasy schodzą do
    tego samego `repository._range_start`, więc rozjazd list byłby błędem
    typu „422 na `1M`, które gdzie indziej działa". Import trasy z trasy nie
    tworzy cyklu (`portfolio.routes` nie zna `analytics`) i niczego nie
    rejestruje — routery wpina jawnie `app/main.py`.
    """
    result = await service.performance(
        db,
        portfolio,
        range_=range_.value,
        benchmark=None if benchmark is None else benchmark.value,
    )
    return PerformanceOut(
        range=result.range,
        period_return=result.period_return,
        first_date=result.first_date,
        last_date=result.last_date,
        links=result.links,
        skipped_composition_change=result.skipped_composition_change,
        skipped_zero_base=result.skipped_zero_base,
        points=[
            PerformancePointOut(date=p.date, value_pln=p.value_pln, ret=p.ret, index=p.index)
            for p in result.points
        ],
        benchmark=(
            None
            if result.benchmark is None
            else BenchmarkOut(
                key=result.benchmark.key,
                symbol=result.benchmark.symbol,
                label=result.benchmark.label,
                currency=result.benchmark.currency,
                approximate=result.benchmark.approximate,
                note=result.benchmark.note,
                unavailable_reason=result.benchmark.unavailable_reason,
                outperformance=result.benchmark.outperformance,
                points=[
                    BenchmarkPointOut(date=p.date, as_of=p.as_of, index=p.index)
                    for p in result.benchmark.points
                ],
            )
        ),
    )


@router.get("/portfolios/{portfolio_id}/risk", response_model=RiskOut)
async def get_risk(
    portfolio: PortfolioDep,
    db: DbSession,
    range_: Annotated[ValuationRangeParam, Query(alias="range")] = ValuationRangeParam.MAX,
    benchmark: Annotated[BenchmarkParam | None, Query()] = None,
) -> RiskOut:
    """Zmienność, Sharpe, max drawdown + underwater, beta i heatmapa
    miesięczna (krok 41b, etap 8).

    Wszystko liczone z tej samej serii co `/performance` — ogniwa i indeks
    łańcuchowy ze snapshotów, nigdy `value_pln` (ADR-101): wpłata to nie
    zmienność i nie wyjście z obsunięcia.

    `benchmark` jest wymagany **tylko dla bety** — bez niego reszta metryk
    liczy się normalnie, a `beta` jest `null`. Ten sam enum co
    w `/performance`, żeby wybór benchmarku na dashboardzie znaczył to samo
    na wykresie i we wskaźniku.

    Sharpe używa historycznej stopy referencyjnej NBP (krok 41a), zmiennej
    w czasie; przy braku stopy zwracamy `null` z powodem, nigdy liczbę
    policzoną z podstawionego zera.
    """
    result = await service.risk(
        db,
        portfolio,
        range_=range_.value,
        benchmark=None if benchmark is None else benchmark.value,
    )
    return RiskOut(
        range=result.range,
        first_date=result.first_date,
        last_date=result.last_date,
        observations=result.observations,
        min_observations=result.min_observations,
        volatility=result.volatility,
        volatility_unavailable_reason=result.volatility_unavailable_reason,
        sharpe=result.sharpe,
        sharpe_unavailable_reason=result.sharpe_unavailable_reason,
        risk_free_label=result.risk_free_label,
        max_drawdown=(
            None
            if result.max_drawdown is None
            else DrawdownOut(
                value=result.max_drawdown.value,
                peak_date=result.max_drawdown.peak_date,
                trough_date=result.max_drawdown.trough_date,
                recovered_at=result.max_drawdown.recovered_at,
            )
        ),
        underwater=[UnderwaterPointOut(date=p.date, value=p.value) for p in result.underwater],
        monthly_returns=[
            MonthlyReturnOut(year=m.year, month=m.month, ret=m.ret, links=m.links)
            for m in result.monthly_returns
        ],
        beta=(
            None
            if result.beta is None
            else BetaOut(
                key=result.beta.key,
                symbol=result.beta.symbol,
                label=result.beta.label,
                approximate=result.beta.approximate,
                value=result.beta.value,
                observations=result.beta.observations,
                unavailable_reason=result.beta.unavailable_reason,
            )
        ),
    )


def _split_tags(raw: str | None) -> list[str] | None:
    """`?tags=a,b` → `["a", "b"]`. Puste `?tags=` znaczy „bez filtra",
    a nie „filtr, który nic nie przepuszcza" — pusty parametr to zwykle
    wyczyszczony input, nie świadome pytanie o pustkę."""
    if raw is None:
        return None
    names = [name.strip() for name in raw.split(",") if name.strip()]
    return names or None


@router.get("/portfolios/{portfolio_id}/allocation", response_model=AllocationOut)
async def get_allocation(
    portfolio: PortfolioDep,
    db: DbSession,
    by: Annotated[AllocationDimensionParam, Query()],
    tags: Annotated[str | None, Query()] = None,
) -> AllocationOut:
    """`by` jest wymagany (kontrakt nie definiuje domyślnego wymiaru
    alokacji — decyzja: brak wartości domyślnej, 422 zamiast cichego
    zgadywania, którą alokację użytkownik chciał zobaczyć).

    `tags` to opcjonalna lista nazw po przecinku (krok 43). Zawęża portfel
    do aktywów oznaczonych **którymkolwiek** z tych tagów (OR) przed
    policzeniem wag. Nieznana nazwa nic nie wnosi — nie jest błędem,
    bo tag mógł zniknąć w innej karcie przeglądarki.
    """
    result = await service.allocation(db, portfolio, by=by.value, tag_names=_split_tags(tags))
    return AllocationOut(
        by=result.by,
        as_of=result.as_of,
        approximate=result.approximate,
        buckets=[
            AllocationBucketOut(key=b.key, value_pln=b.value_pln, weight=b.weight)
            for b in result.buckets
        ],
    )


@router.get("/portfolios/{portfolio_id}/concentration", response_model=ConcentrationOut)
async def get_concentration(portfolio: PortfolioDep, db: DbSession) -> ConcentrationOut:
    result = await service.concentration(db, portfolio)
    return ConcentrationOut(
        top5_share=result.top5_share,
        count=result.count,
        hhi=result.hhi,
        interpretation=result.interpretation,
    )


@router.get("/portfolios/{portfolio_id}/markets", response_model=list[MarketRankingItemOut])
async def get_market_ranking(portfolio: PortfolioDep, db: DbSession) -> list[MarketRankingItemOut]:
    """Ranking rynków wg wagi w wartości wycenionego portfela (krok 30,
    ADR-102) — posortowany malejąco po `weight`. `index=null` dla rynku bez
    indeksu referencyjnego (skill `analityka-struktury`)."""
    items = await service.market_ranking(db, portfolio)
    return [
        MarketRankingItemOut(
            market_code=item.market_code,
            market_name=item.market_name,
            weight=item.weight,
            index=(
                MarketIndexOut(
                    asset_id=item.index.asset_id,
                    symbol=item.index.symbol,
                    value=item.index.value,
                    change_1d=(
                        IndexChangeOut(abs=item.index.change_1d.abs, pct=item.index.change_1d.pct)
                        if item.index.change_1d is not None
                        else None
                    ),
                    as_of=item.index.as_of,
                    series_30d=[
                        PricePointOut(date=p.date, close_adj=p.close_adj)
                        for p in item.index.series_30d
                    ],
                )
                if item.index is not None
                else None
            ),
        )
        for item in items
    ]
