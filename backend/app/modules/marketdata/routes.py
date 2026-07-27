"""Routing modułu `marketdata`.

Plan krok 24 (etap 4): `GET /assets/search`, `GET /meta/freshness`.
Plan krok 30 (etap 6, ADR-102): `GET /markets/{code}/index?range=` — seria
`close_adj` indeksu referencyjnego rynku. `/assets/{id}`, `PATCH
/assets/{id}/metadata` wciąż poza zakresem (kolejne kroki).

Wszystkie trzy endpointy tego pliku są **publiczne** (bez
`Depends(get_current_user)`): `assets`/`markets`/`ingestion_runs`/`prices` to
słowniki/dane globalne, nie zasoby użytkownika (patrz docstring
`app/modules/marketdata/models.py`: „żadny FK w tym pliku nie kaskaduje z
`users`"). Nie ma tu czego chronić `get_owned_*` — nie istnieje właściciel
aktywa, rynku ani jego notowań, a `market_code`/`{code}` w ścieżce nie jest
identyfikatorem zasobu użytkownika (`tests/test_isolation.py` świadomie go
nie łapie — `RESOURCE_PARAMS` zawiera tylko `portfolio_id`/`holding_id`/
`watchlist_id`/`tag_id`). Ten sam wzorzec co `GET /health`: brak zasobu do
izolowania.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Query

from app.db.session import DbSession
from app.modules.marketdata import service
from app.modules.marketdata.schemas import (
    AssetSearchResultOut,
    FreshnessOut,
    MarketFreshnessOut,
    PricePointOut,
)

router = APIRouter(tags=["marketdata"])


class MarketIndexRangeParam(StrEnum):
    """`?range=` w `GET /markets/{code}/index` — sam zestaw wartości i ten
    sam wzorzec 422-na-nieznaną-wartość co `ValuationRangeParam`
    (`modules/portfolio/routes.py`, `GET /valuations`)."""

    ONE_MONTH = "1M"
    THREE_MONTHS = "3M"
    ONE_YEAR = "1Y"
    YTD = "YTD"
    MAX = "max"


# Poniżej dwóch znaków ILIKE '%q%' skanuje niemal całą tabelę i zwraca szum
# (np. "a" trafia w połowę symboli/nazw) — 422 zamiast pustej listy, żeby
# frontend odróżnił „za krótkie zapytanie" (błąd wejścia) od „brak trafień"
# (poprawne zapytanie, pusty wynik), patrz raport zadania.
_SEARCH_QUERY_MIN_LENGTH = 2
_SEARCH_QUERY_MAX_LENGTH = 100


@router.get("/assets/search", response_model=list[AssetSearchResultOut])
async def search_assets(
    db: DbSession,
    background_tasks: BackgroundTasks,
    q: Annotated[
        str, Query(min_length=_SEARCH_QUERY_MIN_LENGTH, max_length=_SEARCH_QUERY_MAX_LENGTH)
    ],
) -> list[AssetSearchResultOut]:
    """Szuka aktywa po symbolu/nazwie (`ILIKE '%q%'`, do 20 trafień).

    Aktywom bez `sector`/`country` zleca uzupełnienie metadanych w tle
    (`BackgroundTasks` → `service.refresh_asset_metadata_background`) —
    odpowiedź HTTP nie czeka na yfinance (może trwać sekundy), kolejne
    wyszukanie tego samego aktywa zobaczy już uzupełnione pola.
    """
    assets = await service.search_assets(db, q)
    for asset in assets:
        if not (asset.sector and asset.country):
            background_tasks.add_task(service.refresh_asset_metadata_background, asset.id)
    return [AssetSearchResultOut.model_validate(asset) for asset in assets]


@router.get("/meta/freshness", response_model=FreshnessOut)
async def get_freshness(db: DbSession) -> FreshnessOut:
    """Świeżość danych EOD per rynek — ostatni `IngestionRun` i próg
    „dzisiaj/wczoraj" (patrz `service.get_markets_freshness`, docstring
    `_is_fresh`). Zwraca wszystkie rynki ze słownika `markets`, nawet te bez
    żadnego przebiegu ingestii (`stale=True`, nie 500).
    """
    freshness = await service.get_markets_freshness(db)
    return FreshnessOut(markets=[MarketFreshnessOut.model_validate(item) for item in freshness])


@router.get("/markets/{code}/index", response_model=list[PricePointOut])
async def get_market_index(
    code: str,
    db: DbSession,
    range_: Annotated[MarketIndexRangeParam, Query(alias="range")] = MarketIndexRangeParam.MAX,
) -> list[PricePointOut]:
    """Seria `close_adj` (rosnąco po dacie) indeksu referencyjnego rynku
    `code` — krok 30, ADR-102. `404`, jeśli `code` nie istnieje w słowniku
    `markets` albo nie ma `index_asset_id` przypisanego (patrz
    `service.get_market_index_series` — to jedno rozróżnienie żyje w
    serwisie, nie tutaj). Bez `get_owned_*`/autoryzacji, patrz docstring
    modułu."""
    prices = await service.get_market_index_series(db, code, range_=range_.value)
    return [PricePointOut.model_validate(p) for p in prices]
