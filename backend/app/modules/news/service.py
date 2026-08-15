"""Logika modułu `news` — feed dla portfela (plan krok 46, etap 9).

Warstwa serwisu zgodnie z CLAUDE.md §8: `routes` waliduje i autoryzuje,
tutaj jest logika, SQL siedzi w `repository.py`.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.news import repository
from app.modules.news.schemas import NewsAssetRefOut, NewsFeedOut, NewsItemOut


async def portfolio_feed(
    db: AsyncSession,
    portfolio_id: UUID,
    *,
    limit: int = 50,
    with_sentiment_only: bool = False,
) -> NewsFeedOut:
    """Newsy dotyczące aktywów z podanego portfela.

    **Izolacja danych nie dzieje się tutaj.** `portfolio_id` przychodzi
    z `get_owned_portfolio`, który już zweryfikował własność (ADR-002,
    skill `izolacja-danych`) — ta funkcja nigdy nie jest wołana z surowym
    identyfikatorem z żądania. Newsy same w sobie nie są własnością
    użytkownika; prywatna jest wyłącznie informacja o tym, **czyje aktywa
    wyznaczyły ten feed** — i lista `assets` przy każdym wpisie, zawężona
    do aktywów tego portfela (`repository.list_news_links`).

    `with_sentiment_only` filtruje po **obecności** oceny, nie po jej
    wartości. Filtr „tylko pozytywne" byłby przy dzisiejszym pokryciu
    sentymentu (praktycznie zero dla GPW) obietnicą bez pokrycia —
    użytkownik dostałby pusty ekran i wniosek, że nic się nie dzieje
    (CLAUDE.md #3.15). Zawężenie robi zapytanie, nie ta funkcja: filtrowanie
    listy już przyciętej przez `LIMIT` gubiło ocenione newsy leżące głębiej
    (patrz `repository.list_news_for_assets`).
    """
    assets = await repository.list_portfolio_asset_ids(db, portfolio_id)
    asset_ids = [asset_id for asset_id, _ in assets]

    news = await repository.list_news_for_assets(
        db, asset_ids, limit=limit, with_sentiment_only=with_sentiment_only
    )
    links = await repository.list_news_links(db, [n.id for n in news], asset_ids)

    covered_ids = await repository.asset_ids_with_any_news(db, asset_ids)
    without_news = sorted(symbol for asset_id, symbol in assets if asset_id not in covered_ids)

    return NewsFeedOut(
        items=[
            NewsItemOut(
                id=n.id,
                title=n.title,
                url=n.url,
                source=n.source,
                published_at=n.published_at,
                summary=n.summary,
                sentiment=n.sentiment,
                sentiment_source=n.sentiment_source,
                assets=[
                    NewsAssetRefOut(symbol=symbol, match_confidence=confidence)
                    for symbol, confidence in links.get(n.id, [])
                ],
            )
            for n in news
        ],
        assets_covered=len(covered_ids),
        assets_without_news=without_news,
    )
