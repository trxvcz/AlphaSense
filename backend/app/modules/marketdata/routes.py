"""Routing modułu `marketdata`.

Plan krok 24 (etap 4): `GET /assets/search`, `GET /meta/freshness`.
`/markets/{code}/index`, `/assets/{id}`, `PATCH /assets/{id}/metadata`
przybędą w kolejnych krokach.

Oba endpointy tego kroku są **publiczne** (bez `Depends(get_current_user)`):
`assets`/`markets`/`ingestion_runs` to słowniki globalne, nie zasoby
użytkownika (patrz docstring `app/modules/marketdata/models.py`: „żadny FK
w tym pliku nie kaskaduje z `users`"). Nie ma tu czego chronić `get_owned_*`
— nie istnieje właściciel aktywa ani rynku, a wyszukiwarka aktywów musi
działać, zanim użytkownik ma jakikolwiek portfel (dodawanie pierwszej
pozycji). To pierwszy publiczny endpoint pod `/api` w tym repo — nie jest to
przeoczenie autoryzacji, tylko świadoma decyzja tego kroku (patrz raport
zadania), zgodna z resztą kontraktu (`GET /health` jest publiczne z tego
samego powodu: brak zasobu do izolowania).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Query

from app.db.session import DbSession
from app.modules.marketdata import service
from app.modules.marketdata.schemas import AssetSearchResultOut, FreshnessOut, MarketFreshnessOut

router = APIRouter(tags=["marketdata"])

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
