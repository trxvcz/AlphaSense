"""Logika serwisowa modułu `marketdata` niezwiązana z jednym providerem —
metadane aktywów, wyszukiwanie aktywów, świeżość danych EOD i przykładowa
kompozycja `FallbackChain` per rynek (plan kroki 22 i 24, etap 4).

**`ensure_asset_metadata`** to gotowa funkcja z kroku 22, użyta tutaj przez
`refresh_asset_metadata_background` (krok 24, `/assets/search`).

**`build_fallback_chain`** to kompozycja providerów per rynek — wołana przez
worker EOD (`worker/jobs/ingest_market.py`, plan krok 23), rozszerzona tam o
gałęzie `FX`/`COMMODITY` (NBP), patrz TODO/uwagi w docstringu funkcji.

**`search_assets`/`get_markets_freshness`** to logika kroku 24
(`GET /assets/search`, `GET /meta/freshness`) — `routes.py` woła wyłącznie
te dwie funkcje (plus `refresh_asset_metadata_background` jako
`BackgroundTasks`), zero SQL bezpośrednio w routingu (skill `fastapi-modul`).

**`get_market_index_series`** to logika kroku 30 (etap 6, ADR-102):
`GET /markets/{code}/index?range=`. Trasa **publiczna** (bez
`get_owned_*`/`get_current_user`) — `market_code` nie jest zasobem
użytkownika, tak jak `search_assets`/`get_markets_freshness` wyżej.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import NotFoundError
from app.db.session import AsyncSessionLocal
from app.modules.marketdata import repository
from app.modules.marketdata.models import Asset, Price
from app.modules.marketdata.providers.binance import BinanceProvider
from app.modules.marketdata.providers.circuit_breaker import CircuitBreaker
from app.modules.marketdata.providers.finnhub import FinnhubProvider
from app.modules.marketdata.providers.guarded import Guarded
from app.modules.marketdata.providers.nbp import NbpProvider
from app.modules.marketdata.providers.rate_limiter import RateLimiter
from app.modules.marketdata.providers.stooq import StooqProvider
from app.modules.marketdata.providers.yfinance import YFinanceProvider

logger = structlog.get_logger(__name__)

_YFINANCE_PROVIDER_NAME = "yfinance"
_SEARCH_RESULT_LIMIT = 20


async def ensure_asset_metadata(db: AsyncSession, asset: Asset) -> None:
    """Uzupełnia `asset.sector`/`asset.country` z yfinance (jedyny dostawca
    metadanych zbudowany w tym kroku — `Capability.METADATA`, patrz
    `YFinanceProvider`), jeśli oba pola są jeszcze puste.

    Nie robi nic (wraca po cichu, tylko log), jeśli:
    - `asset` ma już oba pola uzupełnione (nadpisanie użytkownika/istniejące
      dane mają pierwszeństwo — ta funkcja tylko dogląda braki),
    - brak mapowania `asset_source_map` dla `(asset.id, "yfinance")`,
    - yfinance zawiedzie albo zwróci `None` (SKILL `data-provider`:
      „yfinance ... potrafi milczeć" — brak metadanych nie jest błędem
      krytycznym, `asset` nadal istnieje i jest wyceniany na cenie, nie na
      metadanych).

    Celowo **bez** `db.commit()` — `asset` jest już śledzony przez sesję
    `db` przekazaną przez wołającego (obiekt ORM), więc mutacja atrybutów
    wystarczy, żeby SQLAlchemy odesłało `UPDATE` przy najbliższym flush/
    commit; commitowanie tutaj założyłoby, że to jedyna zmiana w
    transakcji wołającego, co nie musi być prawdą (np. krok 24 może
    commitować razem z innymi zmianami tego samego żądania).
    """
    if asset.sector and asset.country:
        return

    provider_symbol = await repository.get_provider_symbol(db, asset.id, _YFINANCE_PROVIDER_NAME)
    if provider_symbol is None:
        logger.info(
            "marketdata.ensure_asset_metadata.no_mapping",
            asset_id=str(asset.id),
            provider=_YFINANCE_PROVIDER_NAME,
        )
        return

    provider = YFinanceProvider()
    try:
        metadata = await provider.get_metadata(provider_symbol)
    except Exception as exc:  # yfinance potrafi zawieść na wiele sposobów, patrz SKILL
        logger.warning(
            "marketdata.ensure_asset_metadata.provider_failed",
            asset_id=str(asset.id),
            provider_symbol=provider_symbol,
            error=f"{type(exc).__name__}: {exc}",
        )
        return

    if metadata is None:
        logger.info(
            "marketdata.ensure_asset_metadata.empty",
            asset_id=str(asset.id),
            provider_symbol=provider_symbol,
        )
        return

    if not asset.sector and metadata.sector:
        asset.sector = metadata.sector
    if not asset.country and metadata.country:
        asset.country = metadata.country
    asset.metadata_source = _YFINANCE_PROVIDER_NAME


async def search_assets(db: AsyncSession, query: str) -> list[Asset]:
    """Szuka `assets` po `symbol`/`name` (plan krok 24, `GET /assets/search`).

    Cienka nakładka na `repository.search_assets` — logika trywialna, ale
    żyje tu, nie w `routes.py` (skill `fastapi-modul`: routes nie wołają SQL
    bezpośrednio). Limit wyników (`_SEARCH_RESULT_LIMIT`) jest decyzją
    domenową („ile pokazać w podpowiedzi wyszukiwarki"), nie szczegółem SQL,
    stąd stała tutaj, nie w `repository.py`.
    """
    return await repository.search_assets(db, query, limit=_SEARCH_RESULT_LIMIT)


async def refresh_asset_metadata_background(asset_id: uuid.UUID) -> None:
    """Domyka `sector`/`country` aktywa **po** odpowiedzi HTTP `/assets/search`
    (plan krok 24 — rozszerzenie „przy pierwszym dotknięciu" reguły z kroku
    22 „przy pierwszym dodaniu"; patrz raport zadania).

    Wołana wyłącznie przez `fastapi.BackgroundTasks` z `routes.py` — FastAPI
    uruchamia zadania w tle **po** wysłaniu odpowiedzi, kiedy sesja żądania
    (`DbSession`) jest już zamknięta, dlatego ta funkcja otwiera **własną**
    sesję (`AsyncSessionLocal`) zamiast przyjmować `db` z parametru. Nie
    blokuje odpowiedzi HTTP na czas wywołania do yfinance (CLAUDE.md — wolne
    I/O poza handlerem) i nie podnosi wyjątków dalej — `ensure_asset_metadata`
    już połyka błędy providera, a błąd samej sesji (np. baza niedostępna)
    jest tylko logowany: to zadanie w tle wzbogacające dane, nie krytyczna
    ścieżka żądania, które już dostało odpowiedź 200.
    """
    try:
        async with AsyncSessionLocal() as session:
            asset = await session.get(Asset, asset_id)
            if asset is None:
                logger.info(
                    "marketdata.refresh_asset_metadata_background.asset_gone",
                    asset_id=str(asset_id),
                )
                return
            await ensure_asset_metadata(session, asset)
            await session.commit()
    except Exception as exc:  # zadanie w tle — błąd nie może dotknąć klienta
        logger.warning(
            "marketdata.refresh_asset_metadata_background.failed",
            asset_id=str(asset_id),
            error=f"{type(exc).__name__}: {exc}",
        )


@dataclass(frozen=True, slots=True)
class MarketFreshness:
    """Świeżość danych EOD jednego rynku — wynik `get_markets_freshness`,
    niezależny od `schemas.MarketFreshnessOut` (ten plik nie zna Pydantic/
    HTTP, `routes.py` mapuje jedno na drugie, skill `fastapi-modul`).
    """

    code: str
    name: str
    last_run_at: datetime | None
    status: str | None
    stale: bool


# Świeże = ostatni przebieg ingestii tego rynku zakończył się (`finished_at`
# ustawione, niezależnie od `status` — worker (krok 23) dopiero ustala własne
# słownictwo statusów, ta funkcja świadomie się z nim nie sprzęga) **dzisiaj
# albo wczoraj** (czas serwera, UTC). To prosta reguła, nie kalendarz sesji
# per rynek: GPW/US nie tradują w weekend, więc rynek, którego ostatni
# przebieg to piątek, wypadnie ze świeżości w niedzielę/poniedziałek rano,
# mimo że to wciąż najnowsze dostępne dane — świadomy kompromis (zadanie:
# „nie przekombinuj"), do doprecyzowania po kroku 23 (kalendarz sesji per
# `markets`), jeśli w praktyce da fałszywe alarmy.
def _is_fresh(reference: datetime | None) -> bool:
    if reference is None:
        return False
    today = datetime.now(UTC).date()
    yesterday = today - timedelta(days=1)
    return reference.date() in (today, yesterday)


async def get_markets_freshness(db: AsyncSession) -> list[MarketFreshness]:
    """Świeżość danych EOD dla każdego rynku w słowniku `markets`
    (plan krok 24, `GET /meta/freshness`).

    Rynek bez żadnego `IngestionRun` (np. tuż po `make seed`, przed
    pierwszym uruchomieniem workera) dostaje `stale=True`,
    `last_run_at=None`, `status=None` — stan „nieznana świeżość", nigdy
    500 (CLAUDE.md — brak Redisa/joba nie jest błędem krytycznym).
    """
    markets = await repository.list_markets(db)
    latest_runs = await repository.get_latest_ingestion_runs(db)

    result: list[MarketFreshness] = []
    for market in markets:
        run = latest_runs.get(market.code)
        reference = (run.finished_at or run.started_at) if run is not None else None
        result.append(
            MarketFreshness(
                code=market.code,
                name=market.name,
                last_run_at=reference,
                status=run.status if run is not None else None,
                stale=not _is_fresh(reference),
            )
        )
    return result


async def get_market_index_series(
    db: AsyncSession, market_code: str, *, range_: str
) -> list[Price]:
    """`GET /markets/{code}/index?range=` — seria `close_adj` rosnąco po
    dacie dla indeksu referencyjnego `market_code` (krok 30, ADR-102).

    `NotFoundError` (404), jeśli `market_code` nie istnieje w słowniku
    `markets` **lub** istnieje, ale nie ma `index_asset_id` — w obu
    przypadkach nie ma czego zwrócić (pojęcia „indeks tego rynku" po prostu
    nie ma), więc to brak zasobu, nie pusta lista 200 (patrz raport
    zadania: rozróżnienie „rynek bez indeksu" od „indeks bez jeszcze
    zaciągniętych cen" — to drugie zwraca `200` z pustą/krótką listą, bo
    pojęcie indeksu istnieje, tylko dane EOD jeszcze nie napłynęły).
    """
    market = await repository.get_market(db, market_code)
    if market is None or market.index_asset_id is None:
        raise NotFoundError(f"Rynek {market_code!r} nie ma zdefiniowanego indeksu referencyjnego")

    today = datetime.now(UTC).date()
    return await repository.list_prices_in_range(
        db, market.index_asset_id, range_=range_, today=today
    )


def _guarded(provider_name: str, requests_per_minute: int) -> Guarded:
    provider: BinanceProvider | FinnhubProvider | NbpProvider | StooqProvider | YFinanceProvider
    if provider_name == "binance":
        provider = BinanceProvider()
    elif provider_name == "finnhub":
        provider = FinnhubProvider()
    elif provider_name == "nbp":
        provider = NbpProvider()
    elif provider_name == "stooq":
        provider = StooqProvider()
    else:
        provider = YFinanceProvider()
    return Guarded(
        provider,
        RateLimiter(provider_name, requests_per_minute),
        CircuitBreaker(provider_name),
    )


def build_fallback_chain(market_code: str) -> list[Guarded]:
    """Kolejność providerów per rynek, jako lista `Guarded` gotowa do
    `FallbackChain(build_fallback_chain(market_code))` albo (`FX`/
    `COMMODITY`, patrz niżej) do bezpośredniego użycia przez
    `worker/jobs/ingest_market.py` (plan krok 23 — worker jest tu
    zdefiniowanym wołającym, zgodnie z opcją opisaną w poprzedniej wersji
    tego docstringu: „worker zdecyduje, czy użyć jej wprost, czy zbudować
    własną"; zdecydował, że wprost, rozszerzając ją o `FX`/`COMMODITY`).

    **Znana uproszczona kolejność:** dla każdego `market_code` kolejność
    dostawców jest tu zahardkodowana per rynek, nie czytana z realnego
    `asset_source_map.priority` per aktywo (SKILL `data-provider`, reguła
    „FallbackChain — kolejność z `asset_source_map.priority`") — w praktyce
    wystarcza, bo wszystkie aktywa jednego rynku dziś używają tych samych
    dostawców w tej samej kolejności (`docs/slownik-rynkow.md`); prawdziwe
    pobieranie priorytetu per `(asset_id, provider)` byłoby przedwczesną
    generalizacją bez drugiego przypadku, który by ją uzasadnił. Ta funkcja
    pokazuje za to jedną rzecz, którą nadal warto robić przy budowie
    łańcucha niezależnie od źródła kolejności: **pomijanie Finnhub, gdy
    brak klucza API**, żeby nie marnować próby/logów na pewną porażkę
    (`FinnhubProvider.get_ohlcv` i tak zgłosiłby `ProviderUnavailableError`
    sam, ale lepiej nie pytać w ogóle niż pytać i dostać przewidywalną
    porażkę — patrz `finnhub.py`, docstring modułu).

    **`FX`/`COMMODITY` — wyłącznie NBP:** kursy walut i złoto pochodzą
    wyłącznie z NBP (CLAUDE.md #3.5) — jednoelementowy łańcuch, bez
    fallbacku (żaden inny darmowy dostawca w tym projekcie nie publikuje
    tabeli A NBP ani ceny złota NBP). Dla `FX` łańcuch trafia bezpośrednio
    do `FallbackChain.get_fx`/`Guarded.get_fx` w workerze (kod waluty ISO
    jest tym samym „symbolem" dla każdego potencjalnego przyszłego
    dostawcy FX, w odróżnieniu od OHLCV — patrz `worker/jobs/
    ingest_market.py`, docstring modułu).
    """
    settings = get_settings()

    if market_code == "CRYPTO":
        return [
            _guarded("binance", settings.rate_limit_binance),
            _guarded("yfinance", settings.rate_limit_yfinance),  # symbol BTC-USD
        ]

    if market_code == "GPW":
        return [
            _guarded("stooq", settings.rate_limit_stooq),
            _guarded("yfinance", settings.rate_limit_yfinance),
        ]

    if market_code in {"FX", "COMMODITY"}:
        return [_guarded("nbp", settings.rate_limit_nbp)]

    # rynki zagraniczne (US/US_TECH/XETRA/LSE/EURONEXT/SIX/TSE/HKEX/...)
    chain = [_guarded("yfinance", settings.rate_limit_yfinance)]
    if settings.finnhub_api_key:
        chain.append(_guarded("finnhub", settings.rate_limit_finnhub))
    else:
        logger.info(
            "marketdata.build_fallback_chain.finnhub_skipped",
            market_code=market_code,
            reason="brak FINNHUB_API_KEY",
        )
    return chain


__all__ = [
    "MarketFreshness",
    "build_fallback_chain",
    "ensure_asset_metadata",
    "get_market_index_series",
    "get_markets_freshness",
    "refresh_asset_metadata_background",
    "search_assets",
]
