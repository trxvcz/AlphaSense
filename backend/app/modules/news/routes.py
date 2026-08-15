"""Routing modułu `news` (plan krok 46, etap 9).

Feed jest zawsze **w kontekście portfela** — nie ma trasy „wszystkie newsy".
Powód jest produktowy, nie techniczny: wartością tego ekranu jest „co się
dzieje z TWOIMI pozycjami", a nie kolejny agregator wiadomości gospodarczych
(CLAUDE.md §1 — analityka struktury, nie portal). Efekt uboczny jest
bezpieczeństwowy i pożądany: każda trasa przechodzi przez
`get_owned_portfolio`, więc nie istnieje endpoint newsowy bez weryfikacji
własności zasobu.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from app.core.deps import PortfolioDep
from app.db.session import DbSession
from app.modules.news.schemas import NewsFeedOut
from app.modules.news.service import portfolio_feed

router = APIRouter(tags=["news"])


@router.get("/portfolios/{portfolio_id}/news", response_model=NewsFeedOut)
async def get_portfolio_news(
    portfolio: PortfolioDep,
    db: DbSession,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    with_sentiment_only: Annotated[bool, Query()] = False,
) -> NewsFeedOut:
    """Newsy dotyczące aktywów z portfela, od najnowszych.

    `limit` ograniczony do 200 — feed jest ekranem przeglądowym, a nie
    eksportem; wyższa wartość oznaczałaby zapytanie, które i tak nie ma
    czytelnika.
    """
    return await portfolio_feed(
        db,
        portfolio.id,
        limit=limit,
        with_sentiment_only=with_sentiment_only,
    )
