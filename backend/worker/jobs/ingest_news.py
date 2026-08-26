"""Job pobierania newsów (plan krok 46, etap 9).

Wzorzec ze skilla `job-eod`: blokada doradcza Postgresa (dwie repliki
workera nie pobiorą tego samego feedu dwa razy), idempotentny zapis,
jeden padnięty element nie przerywa przebiegu.

**Dlaczego to NIE jest job per rynek**, w odróżnieniu od `ingest_market`.
Feed RSS nie ma rynku ani godziny zamknięcia — Bankier publikuje przez cały
dzień, a jedna depesza potrafi dotyczyć spółki z GPW i z NYSE naraz.
Wiązanie z rynkiem musiałoby więc być sztuczne, a harmonogram i tak nie
wynikałby ze słownika `markets` (ADR-102 dotyczy danych EOD, nie newsów).
Stąd jeden job cykliczny o stałym interwale.

**Dlaczego nie zapisujemy newsów bez dopasowanego aktywa.** News, którego
nie umiemy powiązać z żadnym aktywem w bazie, nie pojawi się w żadnym
feedzie — trafiłby do tabeli wyłącznie po to, żeby w niej rosnąć. Feed
gospodarczy to kilkaset pozycji dziennie, z czego dotyczących naszych
aktywów są jednostki. Zapisujemy więc tylko to, co ma czytelnika.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

import httpx
import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import ProviderUnavailableError
from app.db.advisory_lock import advisory_lock
from app.db.session import OwnerSessionLocal
from app.modules.marketdata.providers.circuit_breaker import CircuitBreaker
from app.modules.marketdata.providers.rate_limiter import RateLimiter
from app.modules.news import repository
from app.modules.news.matching import (
    MatchConfidence,
    build_matcher,
    content_hash,
    match_assets,
)
from app.modules.news.providers.alphavantage_news import AlphaVantageNewsProvider
from app.modules.news.providers.base import GuardedNews, NewsItem
from app.modules.news.providers.finnhub_news import FinnhubNewsProvider
from app.modules.news.providers.rss import RssProvider, build_rss_client

logger = structlog.get_logger(__name__)


async def ingest_news() -> None:
    """Pobiera newsy z feedów RSS i z Finnhuba, wiążąc je z aktywami.

    Blokada doradcza na stałym kluczu (nie na dacie, jak przy snapshotach):
    ten job jest cykliczny w ciągu dnia, więc kluczem jest sam job, a nie
    doba. Dwa równoległe przebiegi i tak nie zdublowałyby danych
    (`ON CONFLICT DO NOTHING`), ale zdublowałyby ruch do cudzych serwerów.

    **Brak feedów RSS nie wyłącza całego joba.** Ścieżka Finnhuba jest od
    RSS niezależna — pierwsza wersja tej funkcji wychodziła na pustym
    `rss_feed_list`, co po dołożeniu Finnhuba oznaczałoby, że wyłączenie
    polskich feedów w danym środowisku po cichu wyłącza też newsy spółek
    zagranicznych.
    """
    settings = get_settings()
    if not settings.rss_feed_list and not settings.finnhub_api_key:
        logger.info("ingest_news.no_sources_configured")
        return

    logger.info("ingest_news.starting", feeds=len(settings.rss_feed_list))

    async with OwnerSessionLocal() as lock_session:
        async with advisory_lock(lock_session, key="ingest_news") as acquired:
            if not acquired:
                logger.info("ingest_news.lock_not_acquired")
                return
            await _run(settings.news_max_age_days)


async def ingest_news_sentiment() -> None:
    """Pobiera newsy **z oceną sentymentu** z Alpha Vantage.

    **Osobny job, nie trzecia ścieżka w `ingest_news`**, bo różni się tym,
    co dla jobów jest najważniejsze: częstotliwością. Darmowy plan Alpha
    Vantage to 25 zapytań na dobę, a `ingest_news` chodzi co pół godziny
    (48 przebiegów) — wspólny harmonogram wyczerpałby budżet przed
    południem i przez resztę doby dostawca zwracałby komunikat o limicie,
    czyli otwierałby obwód bez powodu. Własny job = własny interwał
    (`worker/scheduler.py`) i własna blokada doradcza.
    """
    settings = get_settings()
    if not settings.alphavantage_api_key:
        logger.info("ingest_news_sentiment.no_api_key")
        return

    async with OwnerSessionLocal() as lock_session:
        async with advisory_lock(lock_session, key="ingest_news_sentiment") as acquired:
            if not acquired:
                logger.info("ingest_news_sentiment.lock_not_acquired")
                return
            await _run_sentiment(settings.news_max_age_days)


@dataclass
class _Counters:
    """Liczniki przebiegu. Osobny typ, bo od dołożenia Finnhuba sumują się
    z dwóch ścieżek i przekazywanie sześciu `int`-ów przez parametry
    zamieniłoby się w błąd kolejności argumentów."""

    fetched: int = 0
    stored: int = 0
    # `upserted`, nie `linked` — `RETURNING` po `ON CONFLICT DO UPDATE`
    # oddaje wiersze wstawione ORAZ zaktualizowane (podniesienie pewności
    # `heuristic → source`), więc ta liczba nie jest liczbą NOWYCH powiązań.
    # Nazwa mówiąca „linked" kłamałaby w logu przy diagnozowaniu przyrostu.
    upserted: int = 0
    duplicates: int = 0
    # Ile razy ocena dojechała do newsa zapisanego wcześniej BEZ niej.
    # Liczone osobno od `stored`, bo to jedyny sygnał, że job sentymentu
    # robi coś więcej niż podnoszenie `match_confidence` — przy zerze przez
    # kilka przebiegów albo Alpha Vantage nic nie oddaje, albo dedup
    # zjada wpisy, zanim ocena zdąży trafić do bazy.
    sentiment_filled: int = 0
    skipped_old: int = 0
    skipped_unmatched: int = 0


async def _run(max_age_days: int) -> None:
    fetched_at = datetime.now(UTC)
    cutoff = fetched_at - timedelta(days=max_age_days)
    counters = _Counters()

    async with OwnerSessionLocal() as db:
        assets = await repository.list_matchable_assets(db)
        matchers = [build_matcher(a.id, a.symbol, a.name) for a in assets]
        finnhub_symbols = await repository.list_provider_symbols(db, "finnhub")

        # --- ścieżka 1: feedy RSS, dopasowanie heurystyczne ---
        async with build_rss_client() as client:
            rss = GuardedNews(
                RssProvider(client),
                limiter=RateLimiter("rss", get_settings().rate_limit_rss),
                breaker=CircuitBreaker("rss"),
            )
            try:
                items = await rss.get_news()
            except ProviderUnavailableError as exc:
                # Padnięty dostawca nie może zatrzymać całego przebiegu —
                # druga ścieżka jest od niego niezależna.
                logger.error("ingest_news.rss_unavailable", error=str(exc))
                items = []

        counters.fetched += len(items)
        for item in items:
            asset_ids = match_assets(item.title, item.summary, matchers)
            await _store(
                db,
                item=item,
                asset_ids=asset_ids,
                confidence=MatchConfidence.HEURISTIC,
                fetched_at=fetched_at,
                cutoff=cutoff,
                counters=counters,
            )

        # --- ścieżka 2: Finnhub per symbol, powiązanie od źródła ---
        if finnhub_symbols:
            async with httpx.AsyncClient() as client:
                finnhub = GuardedNews(
                    # `lookback_days=2`, nie domyślne 7: ten job chodzi co pół
                    # godziny, więc siedmiodniowe okno oznacza pobieranie
                    # w kółko tego samego (zmierzone: 248 pozycji na symbol
                    # przy pierwszym przebiegu, z czego nowe są jednostki).
                    # Dwa dni dają zapas na weekend i na przestój workera,
                    # a nie przepisują archiwum przy każdym odpaleniu.
                    FinnhubNewsProvider(client, lookback_days=2),
                    limiter=RateLimiter("finnhub_news", get_settings().rate_limit_finnhub),
                    breaker=CircuitBreaker("finnhub_news"),
                )
                for asset_id, provider_symbol in finnhub_symbols:
                    try:
                        symbol_items = await finnhub.get_news(symbol=provider_symbol)
                    except ProviderUnavailableError as exc:
                        logger.warning(
                            "ingest_news.finnhub_unavailable",
                            symbol=provider_symbol,
                            error=str(exc),
                        )
                        break  # obwód otwarty — kolejne symbole i tak padną
                    counters.fetched += len(symbol_items)
                    for item in symbol_items:
                        await _store(
                            db,
                            item=item,
                            asset_ids=[asset_id],
                            confidence=MatchConfidence.SOURCE,
                            fetched_at=fetched_at,
                            cutoff=cutoff,
                            counters=counters,
                        )

        await db.commit()

    logger.info(
        "ingest_news.finished",
        fetched=counters.fetched,
        stored=counters.stored,
        upserted=counters.upserted,
        duplicates=counters.duplicates,
        sentiment_filled=counters.sentiment_filled,
        skipped_old=counters.skipped_old,
        skipped_unmatched=counters.skipped_unmatched,
    )


async def _run_sentiment(max_age_days: int) -> None:
    fetched_at = datetime.now(UTC)
    cutoff = fetched_at - timedelta(days=max_age_days)
    counters = _Counters()

    async with OwnerSessionLocal() as db:
        mappings = await repository.list_provider_symbols(db, "alphavantage")
        if not mappings:
            logger.info("ingest_news_sentiment.no_mapped_assets")
            return
        # Po symbolu dostawcy, wielkimi literami — `NewsItem.symbols` niesie
        # tickery tak, jak zwrócił je Alpha Vantage, a mapowanie w bazie
        # zapisuje je w formie kanonicznej dostawcy.
        by_symbol: dict[str, UUID] = {}
        for asset_id, symbol in mappings:
            key = symbol.upper()
            if key in by_symbol:
                # PK `asset_source_map` to `(asset_id, provider)`, więc nic nie
                # zabrania dwóm aktywom dzielić `provider_symbol` (ten sam
                # ticker na dwóch rynkach, ADR-y). Wygrywa jedno, a które —
                # zależy od kolejności wierszy, czyli byłoby niedeterministyczne
                # między przebiegami. Nie zgadujemy: głośno o tym mówimy.
                logger.warning(
                    "ingest_news_sentiment.duplicate_provider_symbol",
                    symbol=key,
                    kept=str(by_symbol[key]),
                    dropped=str(asset_id),
                )
                continue
            by_symbol[key] = asset_id

        async with httpx.AsyncClient() as client:
            provider = AlphaVantageNewsProvider(client)
            guarded = GuardedNews(
                provider,
                limiter=RateLimiter(provider.name, get_settings().rate_limit_alphavantage),
                breaker=CircuitBreaker(provider.name),
            )
            # Wołamy providera bezpośrednio przez `get_news_batch` (jedno
            # zapytanie na wszystkie symbole — patrz docstring providera),
            # ale przez `GuardedNews._guarded_call`, żeby limiter i obwód
            # obowiązywały tak samo jak przy `get_news`.
            try:
                items = await guarded.get_news_batch(list(by_symbol))
            except ProviderUnavailableError as exc:
                logger.error("ingest_news_sentiment.unavailable", error=str(exc))
                return

        counters.fetched += len(items)
        for item in items:
            asset_ids = [by_symbol[s] for s in item.symbols if s in by_symbol]
            await _store(
                db,
                item=item,
                asset_ids=asset_ids,
                # Powiązanie podał dostawca (`ticker_sentiment`), nie nasze
                # dopasowanie tekstu — to fakt, nie przybliżenie.
                confidence=MatchConfidence.SOURCE,
                fetched_at=fetched_at,
                cutoff=cutoff,
                counters=counters,
            )

        await db.commit()

    logger.info(
        "ingest_news_sentiment.finished",
        fetched=counters.fetched,
        stored=counters.stored,
        upserted=counters.upserted,
        duplicates=counters.duplicates,
        sentiment_filled=counters.sentiment_filled,
        skipped_old=counters.skipped_old,
        skipped_unmatched=counters.skipped_unmatched,
    )


async def _store(
    db: AsyncSession,
    *,
    item: NewsItem,
    asset_ids: list[UUID],
    confidence: MatchConfidence,
    fetched_at: datetime,
    cutoff: datetime,
    counters: _Counters,
) -> None:
    """Zapisuje jeden news i jego powiązania. Wspólne dla obu ścieżek.

    **Duplikat nadal dostaje powiązania.** To zmiana względem pierwszej
    wersji, w której duplikat kończył przetwarzanie: ten sam news potrafi
    przyjść z RSS (heurystycznie) i z Finnhuba (od źródła), a wtedy drugie
    wejście musi mieć szansę podnieść `match_confidence` na `source`
    (`link_news_to_assets`). Pominięcie tego kroku zostawiłoby fakt
    oznaczony jako przybliżenie tylko dlatego, że RSS był pierwszy.
    """
    if item.published_at < cutoff:
        counters.skipped_old += 1
        return
    if not asset_ids:
        counters.skipped_unmatched += 1
        return

    digest = content_hash(item.title, item.published_at)
    news_id = await repository.upsert_news(
        db,
        title=item.title,
        url=item.url,
        source=item.source,
        published_at=item.published_at,
        fetched_at=fetched_at,
        content_hash=digest,
        summary=item.summary,
        sentiment=item.sentiment,
        sentiment_source=item.sentiment_source,
    )
    if news_id is None:
        counters.duplicates += 1
        # Konflikt mógł paść na jednym z DWÓCH ograniczeń, więc szukamy po
        # obu. `content_hash` to przypadek „ta sama depesza pod innym
        # adresem" — PAP-owa informacja z Bankiera i ta sama z Finnhuba.
        # Pominięcie go (pierwsza wersja kończyła tu `return`-em) kosztowało
        # dokładnie to, po co ta ścieżka istnieje: powiązanie od źródła nigdy
        # nie powstawało, bo RSS był pierwszy pod innym URL-em.
        news_id = await repository.get_news_id_by_url(
            db, item.url
        ) or await repository.get_news_id_by_content_hash(db, digest)
        if news_id is None:
            # Wiersz zniknął między `INSERT` a odczytem (równoległy przebieg
            # + czyszczenie). Nie ma czego wiązać.
            return
        # Duplikat mógł przyjść z oceną, której wiersz w bazie nie ma —
        # tak wygląda normalny przebieg `ingest_news_sentiment` dla depeszy
        # zapisanej wcześniej przez RSS albo Finnhuba. `upsert_news` wyżej
        # sam z siebie tej oceny nie dowiezie (`DO NOTHING`), więc bez tego
        # kroku sentyment ginie i feed kłamie, że nikt newsa nie ocenił.
        if item.sentiment is not None and item.sentiment_source is not None:
            if await repository.fill_missing_sentiment(
                db,
                news_id=news_id,
                sentiment=item.sentiment,
                sentiment_source=item.sentiment_source,
            ):
                counters.sentiment_filled += 1
    else:
        counters.stored += 1

    counters.upserted += await repository.link_news_to_assets(
        db,
        news_id=news_id,
        asset_ids=asset_ids,
        published_at=item.published_at,
        match_confidence=confidence,
    )
