"""Zapis i odczyt newsów (plan krok 46, etap 9).

Ten sam kształt co `marketdata/repository.py`: wąskie funkcje przyjmujące
`AsyncSession`, bez klasy „repozytorium", zapis zawsze przez
`INSERT ... ON CONFLICT DO NOTHING` — ponowny przebieg joba za ten sam
dzień ma nie duplikować (CLAUDE.md #3.9).

**`DO NOTHING`, nie `DO UPDATE`** — inaczej niż przy cenach. Cena za dany
dzień bywa korygowana przez dostawcę i nadpisanie jest pożądane; treść
depeszy już opublikowanej się nie zmienia, a gdyby serwis po cichu
przeredagował tytuł, nadpisanie zmieniłoby `content_hash` istniejącego
wiersza i rozspójniło deduplikację. Pierwsza wersja wygrywa.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.marketdata.models import Asset, AssetSourceMap
from app.modules.news.matching import MatchConfidence
from app.modules.news.models import News, NewsAsset
from app.modules.portfolio.models import Holding


async def list_matchable_assets(db: AsyncSession) -> list[Asset]:
    """Aktywa, do których wolno przypiąć news.

    Tylko `is_active` — aktywa wycofane z obrotu nie mają po co zbierać
    newsów, a zostają w bazie ze względu na historyczne wyceny.
    """
    result = await db.execute(select(Asset).where(Asset.is_active.is_(True)))
    return list(result.scalars().all())


async def list_provider_symbols(db: AsyncSession, provider: str) -> list[tuple[UUID, str]]:
    """Aktywa mające mapowanie na danego dostawcę: `(asset_id, symbol_u_dostawcy)`.

    Job newsowy pyta Finnhuba **wyłącznie o to**, co Finnhub realnie pokrywa.
    Bez tego filtra lecielibyśmy z zapytaniem o `CDR` i `PKN` (GPW, spoza
    zakresu Finnhuba), dostając puste listy i paląc limit zapytań.

    Zapytanie dotyczy tabel modułu `marketdata`, ale mieszka tutaj, bo jego
    jedynym konsumentem jest ingestia newsów — tak samo jak
    `list_matchable_assets` wyżej.
    """
    result = await db.execute(
        select(AssetSourceMap.asset_id, AssetSourceMap.provider_symbol)
        .join(Asset, Asset.id == AssetSourceMap.asset_id)
        .where(AssetSourceMap.provider == provider, Asset.is_active.is_(True))
    )
    return [(row.asset_id, row.provider_symbol) for row in result]


async def upsert_news(
    db: AsyncSession,
    *,
    title: str,
    url: str,
    source: str,
    published_at: datetime,
    fetched_at: datetime,
    content_hash: str,
    summary: str | None,
    sentiment: Decimal | None = None,
    sentiment_source: str | None = None,
) -> UUID | None:
    """Zapisuje news i zwraca jego `id`, albo `None`, gdy to duplikat.

    Zwracane `None` jest istotne dla wołającego: news odrzucony jako
    duplikat **nie ma być ponownie tagowany**, bo powiązania z aktywami
    już istnieją. Bez tego rozróżnienia job przy każdym przebiegu
    przepisywałby `news_assets` dla całego okna feedu.

    Konflikt może paść na jednym z dwóch ograniczeń (`url` albo
    `content_hash`), więc nie da się użyć `index_elements` dla obu naraz
    w jednym `ON CONFLICT` — stąd `DO NOTHING` bez wskazania indeksu,
    które łapie każdy z nich.
    """
    statement = (
        insert(News)
        .values(
            title=title,
            url=url,
            source=source,
            published_at=published_at,
            fetched_at=fetched_at,
            content_hash=content_hash,
            summary=summary,
            sentiment=sentiment,
            sentiment_source=sentiment_source,
        )
        .on_conflict_do_nothing()
        .returning(News.id)
    )
    result = await db.execute(statement)
    row = result.scalar_one_or_none()
    return row


async def fill_missing_sentiment(
    db: AsyncSession,
    *,
    news_id: UUID,
    sentiment: Decimal,
    sentiment_source: str,
) -> bool:
    """Dopisuje ocenę do newsa, który jeszcze żadnej nie ma. Zwraca, czy zapisano.

    **Wyjątek od zasady „pierwsza wersja wygrywa"** z `upsert_news`, i to
    wyjątek wąski z wyboru. Tamta zasada broni treści: tytuł i zajawka mają
    zostać takie, jak podał wydawca, który był pierwszy. Sentyment jest inny
    — pierwsze źródło (RSS Bankiera, Finnhub `/company-news`) go **w ogóle
    nie ma**, więc `ON CONFLICT DO NOTHING` nie chronił tu żadnej wartości,
    tylko wyrzucał jedyną, jaka kiedykolwiek przyszła. Skutek był taki, że
    `?with_sentiment_only=true` pokazywał pustkę, a UI twierdziło „nikt tego
    nie ocenił" — dokładnie to przekłamanie, przed którym broni CLAUDE.md
    #3.15, tylko odwrócone.

    `WHERE sentiment IS NULL` jest częścią kontraktu, nie optymalizacją:
    ocena raz zapisana nie ma być nadpisywana przy kolejnym przebiegu, bo
    wtedy wartość w bazie zależałaby od kolejności jobów, a nie od danych.
    Warunek jest w SQL-u, więc rozstrzyga go baza — sprawdzenie w Pythonie
    przegrałoby z równoległym przebiegiem drugiego workera.
    """
    statement = (
        update(News)
        .where(News.id == news_id, News.sentiment.is_(None))
        .values(sentiment=sentiment, sentiment_source=sentiment_source)
        .returning(News.id)
    )
    result = await db.execute(statement)
    return result.scalar_one_or_none() is not None


async def get_news_id_by_url(db: AsyncSession, url: str) -> UUID | None:
    """`id` newsu o podanym adresie, albo `None`, gdy go nie ma.

    Potrzebne wyłącznie po odrzuconym `upsert_news` (patrz `_store`
    w `worker/jobs/ingest_news.py`). Ten sam news potrafi przyjść dwiema
    drogami — z RSS (dopasowany heurystycznie) i z Finnhuba (powiązany przez
    źródło) — a `ON CONFLICT DO NOTHING` nie oddaje `id` wiersza, który już
    istniał. Bez tego zapytania drugie wejście nie miałoby czego podnieść
    na `match_confidence = 'source'` i fakt zostałby oznaczony jako
    przybliżenie tylko dlatego, że RSS był pierwszy.
    """
    result = await db.execute(select(News.id).where(News.url == url))
    return result.scalar_one_or_none()


async def get_news_id_by_content_hash(db: AsyncSession, content_hash: str) -> UUID | None:
    """`id` newsu o podanym `content_hash`, albo `None`, gdy go nie ma.

    Bliźniak `get_news_id_by_url` dla drugiego z dwóch ograniczeń
    unikalności. Konflikt na `content_hash` (a nie na `url`) oznacza **tę
    samą depeszę pod innym adresem** — czyli dokładnie sytuację, w której
    PAP-owa informacja przyszła najpierw z Bankiera (dopasowana
    heurystycznie), a potem z Finnhuba/Alpha Vantage z powiązaniem od
    źródła. Bez tego zapytania druga droga kończyła się `return`-em przed
    `link_news_to_assets` i pewne powiązanie nigdy nie powstawało.
    """
    result = await db.execute(select(News.id).where(News.content_hash == content_hash))
    return result.scalar_one_or_none()


async def list_portfolio_asset_ids(db: AsyncSession, portfolio_id: UUID) -> list[tuple[UUID, str]]:
    """Aktywa z pozycji danego portfela: `(asset_id, symbol)`.

    Zapytanie dotyczy tabel modułów `marketdata` i `portfolio`, ale mieszka
    tutaj, bo jego jedynym konsumentem jest feed newsów — tak samo jak
    `list_matchable_assets` i `list_provider_symbols` wyżej. Serwis ma wołać
    repozytorium, nie składać SQL-a (CLAUDE.md §8).

    **To nie jest miejsce, w którym dzieje się izolacja danych.**
    `portfolio_id` przychodzi z `get_owned_portfolio`; ta funkcja nigdy nie
    jest wołana z surowym identyfikatorem z żądania.
    """
    result = await db.execute(
        select(Asset.id, Asset.symbol)
        .join(Holding, Holding.asset_id == Asset.id)
        .where(Holding.portfolio_id == portfolio_id)
    )
    return [(row.id, row.symbol) for row in result]


async def asset_ids_with_any_news(db: AsyncSession, asset_ids: list[UUID]) -> set[UUID]:
    """Które z podanych aktywów mają w ogóle jakikolwiek powiązany news.

    Liczone osobnym zapytaniem, a nie z pobranej listy feedu: feed jest
    przycięty przez `limit`, więc aktywo z newsami sprzed tygodnia wypadłoby
    poza okno i zostałoby błędnie policzone jako „bez newsów".
    """
    if not asset_ids:
        return set()
    result = await db.execute(
        select(NewsAsset.asset_id).where(NewsAsset.asset_id.in_(asset_ids)).distinct()
    )
    return set(result.scalars().all())


async def link_news_to_assets(
    db: AsyncSession,
    *,
    news_id: UUID,
    asset_ids: list[UUID],
    published_at: datetime,
    match_confidence: MatchConfidence = MatchConfidence.HEURISTIC,
) -> int:
    """Wiąże news z aktywami, pomijając powiązania już istniejące.

    `published_at` jest zdenormalizowane do `news_assets` celowo (patrz
    docstring modelu) — feed sortuje po nim bez dotykania tabeli `news`.

    **Konflikt podnosi pewność, nigdy jej nie obniża.** Ten sam news może
    trafić do nas dwiema drogami: z RSS (dopasowany heurystycznie) i z
    Finnhuba (powiązany przez źródło). Zwykłe `DO NOTHING` zostawiłoby
    wtedy `heuristic` tylko dlatego, że RSS był pierwszy — czyli
    oznaczyłoby fakt jako przybliżenie. Stąd `DO UPDATE`, ale wyłącznie
    w kierunku `heuristic → source`; odwrotna kolejność niczego nie psuje,
    bo warunek jej nie przepuści.
    """
    if not asset_ids:
        return 0
    # `.returning()` NA KOŃCU, po `on_conflict_do_update` — odwrotna
    # kolejność zwraca `ReturningInsert`, które nie ma już ani
    # `on_conflict_do_update`, ani `excluded` (mypy to wyłapuje, SQLAlchemy
    # w runtime też).
    statement = insert(NewsAsset).values(
        [
            {
                "news_id": news_id,
                "asset_id": asset_id,
                "published_at": published_at,
                "match_confidence": match_confidence.value,
            }
            for asset_id in asset_ids
        ]
    )
    upsert = statement.on_conflict_do_update(
        index_elements=["news_id", "asset_id"],
        set_={"match_confidence": statement.excluded.match_confidence},
        where=NewsAsset.match_confidence != MatchConfidence.SOURCE.value,
    ).returning(NewsAsset.asset_id)
    result = await db.execute(upsert)
    return len(result.scalars().all())


async def list_news_for_assets(
    db: AsyncSession,
    asset_ids: list[UUID],
    *,
    limit: int = 50,
    with_sentiment_only: bool = False,
) -> list[News]:
    """Najnowsze newsy dotyczące podanych aktywów.

    `DISTINCT` po `news.id` jest konieczne: jedna depesza o WIG20 może być
    powiązana z kilkoma aktywami z tego samego portfela i bez tego
    pojawiłaby się w feedzie tyle razy, ile pozycji dotyczy.

    **`with_sentiment_only` musi zawężać PRZED `LIMIT`, nie po.** Pierwsza
    wersja filtrowała listę już przyciętą w Pythonie i przez to kłamała:
    portfel z przewagą GPW ma wśród 50 najnowszych newsów praktycznie same
    wpisy z polskich feedów, które sentymentu nie niosą, więc filtr zwracał
    pustkę nawet wtedy, gdy ocenione newsy o spółkach zagranicznych leżały
    w bazie dzień głębiej. UI mówił wtedy „żaden news o Twoich pozycjach nie
    ma oceny wydźwięku" — zdanie fałszywe, którego użytkownik nie miał jak
    rozpoznać (CLAUDE.md #3.15). Przy okazji `limit` znowu znaczy „tyle
    pozycji", niezależnie od filtra.
    """
    if not asset_ids:
        return []
    statement = (
        select(News)
        .join(NewsAsset, NewsAsset.news_id == News.id)
        .where(NewsAsset.asset_id.in_(asset_ids))
    )
    if with_sentiment_only:
        statement = statement.where(News.sentiment.is_not(None))
    result = await db.execute(statement.order_by(News.published_at.desc()).distinct().limit(limit))
    return list(result.scalars().all())


async def list_news_links(
    db: AsyncSession,
    news_ids: list[UUID],
    asset_ids: list[UUID],
) -> dict[UUID, list[tuple[str, str]]]:
    """Powiązania `news → [(symbol_aktywa, pewność)]`, zawężone do `asset_ids`.

    Osobne zapytanie zamiast `JOIN`-a w `list_news_for_assets`: tamto jest
    `DISTINCT ... LIMIT`, więc doklejenie kolumn z `news_assets` rozbiłoby
    jeden news na tyle wierszy, ile aktywów dotyczy, i `LIMIT` przestałby
    znaczyć „tyle newsów".

    **Zawężenie do `asset_ids` jest wymogiem izolacji, nie optymalizacją.**
    Ten sam news bywa powiązany z aktywami spoza portfela pytającego;
    zwrócenie ich symboli powiedziałoby użytkownikowi, co trzymają inni
    (CLAUDE.md #3.2). Feed pokazuje wyłącznie te pozycje, które sam ma.
    """
    if not news_ids or not asset_ids:
        return {}
    result = await db.execute(
        select(NewsAsset.news_id, Asset.symbol, NewsAsset.match_confidence)
        .join(Asset, Asset.id == NewsAsset.asset_id)
        .where(NewsAsset.news_id.in_(news_ids), NewsAsset.asset_id.in_(asset_ids))
        .order_by(Asset.symbol)
    )
    links: dict[UUID, list[tuple[str, str]]] = {}
    for row in result:
        links.setdefault(row.news_id, []).append((row.symbol, row.match_confidence))
    return links
