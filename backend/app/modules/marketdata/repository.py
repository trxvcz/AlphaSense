"""Zapis/odczyt danych rynkowych (`fx_rates`, `prices`) — warstwa dzieląca
się między wszystkich dostawców (plan krok 21, etap 4).

Świadomie osobne, wąskie funkcje zamiast jednej klasy „repozytorium" (skill
`data-provider`, sekcja „Reguły twarde" #3; zadanie kroku 21 wprost prosi o
kształt łatwy do bezkonfliktowego rozszerzania, bo krok 22 — Stooq/yfinance/
Finnhub, inny równoległy agent — dopisze tu kolejne funkcje, np.
`upsert_asset_metadata`). Funkcje w tym module **nie znają** konkretnego
providera (NBP/Stooq/...) — przyjmują już zbudowane DTO (`FxQuote`,
`PriceBar`) i zapisują je idempotentnie.

Zapis zawsze `INSERT ... ON CONFLICT (...) DO UPDATE` (nigdy zwykły
`INSERT`, nigdy „usuń i wstaw ponownie") — ponowne uruchomienie joba EOD za
ten sam dzień nadpisuje, nie duplikuje (CLAUDE.md #3.9).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import UUID

import structlog
from sqlalchemy import or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.marketdata.models import Asset, AssetSourceMap, FxRate, IngestionRun, Market, Price
from app.modules.marketdata.providers.base import FxQuote, PriceBar

logger = structlog.get_logger(__name__)


async def get_rate_pln(db: AsyncSession, currency: str, on_date: date) -> Decimal | None:
    """Kurs `currency` względem PLN obowiązujący w dniu `on_date`.

    Reguła CLAUDE.md #3.5: NBP nie publikuje kursu w weekendy/święta, więc
    zamiast wymagać dokładnego wpisu na `on_date`, cofamy się do
    **najnowszego notowania nie późniejszego niż `on_date`**
    (`max(date) <= D`) — stąd `ORDER BY date DESC LIMIT 1`, nie równość.

    Zwraca `None`, jeśli w `fx_rates` nie ma **żadnego** notowania
    `currency` w dniu `on_date` lub wcześniej (np. baza dopiero zasilana,
    albo literówka w kodzie waluty) — wołający (silnik wyceny, etap 5)
    decyduje, co z tym zrobić (błąd wyceny pozycji, nie cichy `0`).
    """
    stmt = (
        select(FxRate.rate_pln)
        .where(FxRate.currency == currency.upper(), FxRate.date <= on_date)
        .order_by(FxRate.date.desc())
        .limit(1)
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def upsert_fx_rates(db: AsyncSession, quotes: list[FxQuote]) -> None:
    """Zapisuje `quotes` do `fx_rates`, idempotentnie (`ON CONFLICT (currency,
    date) DO UPDATE`) — ponowne uruchomienie ingestii NBP za ten sam zakres
    dat nadpisuje `rate_pln`, nie duplikuje wierszy.

    Uwaga: `quotes` to surowe kursy z dnia notowania — to **nie** jest
    miejsce na logikę `max(date) <= D` (to robi `get_rate_pln` przy
    odczycie, nie zapis: zapisujemy dokładnie te dni, które NBP faktycznie
    opublikował).
    """
    if not quotes:
        logger.info("marketdata.upsert_fx_rates.empty")
        return
    values = [
        {"currency": quote.currency.upper(), "date": quote.date, "rate_pln": quote.rate_pln}
        for quote in quotes
    ]
    stmt = insert(FxRate).values(values)
    stmt = stmt.on_conflict_do_update(
        index_elements=[FxRate.currency, FxRate.date],
        set_={"rate_pln": stmt.excluded.rate_pln},
    )
    await db.execute(stmt)
    await db.commit()
    logger.info("marketdata.upsert_fx_rates.done", count=len(values))


async def upsert_prices(db: AsyncSession, asset_id: UUID, bars: list[PriceBar]) -> None:
    """Zapisuje `bars` do `prices` dla `asset_id`, idempotentnie
    (`ON CONFLICT (asset_id, date) DO UPDATE`).

    Ogólna dla wszystkich providerów OHLCV (NBP/złoto dziś, Stooq/yfinance/
    Finnhub w kroku 22) — providerzy dostarczają `PriceBar`, ten moduł nie
    wie, skąd świeca pochodzi.

    Pilnuje CHECK `close_adj > 0` (baza i tak by odrzuciła cały `INSERT`,
    ale wolimy odsiać pojedynczy zepsuty wiersz z logiem niż stracić zapis
    całej reszty poprawnych dni w tym samym wywołaniu) — świece z
    `close_adj <= 0` są pomijane i logowane jako ostrzeżenie, nie wysyłane
    do bazy.
    """
    if not bars:
        logger.info("marketdata.upsert_prices.empty", asset_id=str(asset_id))
        return

    values = []
    for bar in bars:
        if bar.close_adj <= 0:
            logger.warning(
                "marketdata.upsert_prices.invalid_close_adj",
                asset_id=str(asset_id),
                date=bar.date.isoformat(),
                close_adj=str(bar.close_adj),
            )
            continue
        values.append(
            {
                "asset_id": asset_id,
                "date": bar.date,
                "open": bar.open,
                "high": bar.high,
                "low": bar.low,
                "close": bar.close,
                "close_adj": bar.close_adj,
                "volume": bar.volume,
            }
        )

    if not values:
        logger.warning("marketdata.upsert_prices.all_invalid", asset_id=str(asset_id))
        return

    stmt = insert(Price).values(values)
    stmt = stmt.on_conflict_do_update(
        index_elements=[Price.asset_id, Price.date],
        set_={
            "open": stmt.excluded.open,
            "high": stmt.excluded.high,
            "low": stmt.excluded.low,
            "close": stmt.excluded.close,
            "close_adj": stmt.excluded.close_adj,
            "volume": stmt.excluded.volume,
        },
    )
    await db.execute(stmt)
    await db.commit()
    logger.info("marketdata.upsert_prices.done", asset_id=str(asset_id), count=len(values))


async def list_active_assets(db: AsyncSession, market_code: str) -> list[Asset]:
    """Aktywne aktywa notowane na `market_code`, posortowane po symbolu —
    lista do ingestii EOD (`worker/jobs/ingest_market.py`, plan krok 23).

    `is_active=False` (aktywo wygaszone, patrz `models.py`) jest pomijane —
    nie ma sensu odpytywać dostawców o coś, co już nie powinno być
    aktualizowane; historia w `prices` zostaje nietknięta.
    """
    stmt = (
        select(Asset)
        .where(Asset.market_code == market_code, Asset.is_active.is_(True))
        .order_by(Asset.symbol)
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def list_fx_currencies(db: AsyncSession) -> list[str]:
    """Zbiór walut, dla których trzeba mieć kurs NBP — wyliczony z
    `assets.currency` (aktywnych aktywów), nie z osobnego słownika: rynek
    `FX` (`docs/slownik-rynkow.md`) sam w sobie nie ma żadnych wierszy
    `assets` (nie ma czego zmapować przez `asset_source_map` — kod waluty
    ISO jest już „symbolem" zrozumiałym bezpośrednio dla
    `DataProvider.get_fx`, nic tu nie trzeba tłumaczyć).

    `PLN` pomijane — wycena w PLN nie wymaga przeliczenia kursu (CLAUDE.md
    #3.5 dotyczy walut *obcych*).
    """
    stmt = (
        select(Asset.currency)
        .where(Asset.currency != "PLN", Asset.is_active.is_(True))
        .distinct()
        .order_by(Asset.currency)
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def get_provider_symbol(db: AsyncSession, asset_id: UUID, provider: str) -> str | None:
    """Symbol aktywa u konkretnego dostawcy (`asset_source_map.provider_symbol`),
    albo `None`, jeśli brak mapowania dla tej pary `(asset_id, provider)`
    (plan krok 22, etap 4).

    Jedyne miejsce, w którym wolno odczytać symbol zewnętrzny przed
    wywołaniem `DataProvider.get_ohlcv`/`get_metadata` — zero sklejania
    symbolu w kodzie providera/serwisu (CLAUDE.md #3.4, SKILL
    `data-provider`, reguła 1: „Symbol zewnętrzny wyłącznie z
    `asset_source_map`").
    """
    stmt = select(AssetSourceMap.provider_symbol).where(
        AssetSourceMap.asset_id == asset_id,
        AssetSourceMap.provider == provider,
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def search_assets(db: AsyncSession, query: str, *, limit: int = 20) -> list[Asset]:
    """Szuka `assets` po `symbol`/`name`, `ILIKE '%query%'` (case-insensitive,
    plan krok 24, etap 4).

    Tylko `is_active=True` — aktywa wygaszone (`is_active=False`, patrz
    docstring `Asset` w `models.py`) nadal istnieją dla historii `prices`/
    `holdings`, ale nie mają sensu jako wynik wyszukiwania „dodaj pozycję".
    `query` jest już zwalidowane przez `routes.py` (min. długość) — ta
    funkcja nie zna reguł walidacji wejścia HTTP, tylko wykonuje zapytanie.
    """
    pattern = f"%{query}%"
    stmt = (
        select(Asset)
        .where(
            Asset.is_active.is_(True),
            or_(Asset.symbol.ilike(pattern), Asset.name.ilike(pattern)),
        )
        .order_by(Asset.symbol)
        .limit(limit)
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def list_markets(db: AsyncSession) -> list[Market]:
    """Wszystkie rynki ze słownika `markets`, posortowane po `code` — bez
    `LIMIT`, tabela ma kilkanaście wierszy (ADR-102), nie rośnie z ruchem
    użytkowników.
    """
    result = await db.execute(select(Market).order_by(Market.code))
    return list(result.scalars().all())


async def get_latest_ingestion_runs(db: AsyncSession) -> dict[str, IngestionRun]:
    """Ostatni `IngestionRun` (po `started_at DESC`) per `market_code`,
    w jednym zapytaniu (`DISTINCT ON`, Postgres) zamiast N+1 — podstawa
    `GET /meta/freshness`.

    Rynki bez żadnego przebiegu ingestii po prostu nie mają klucza w
    zwróconym słowniku (wołający, `service.get_markets_freshness`, traktuje
    to jako „świeżość nieznana", nie błąd).
    """
    stmt = (
        select(IngestionRun)
        .distinct(IngestionRun.market_code)
        .order_by(IngestionRun.market_code, IngestionRun.started_at.desc())
    )
    result = await db.execute(stmt)
    return {run.market_code: run for run in result.scalars().all()}
