"""Routing modułu `dividends` (plan krok 47, etap 9).

Kalendarz jest zawsze **w kontekście portfela**, tak samo jak feed newsów
z kroku 46: wartością tego ekranu jest „co czeka MOJE pozycje", a nie
kalendarz dywidend całego rynku. Efekt uboczny jest bezpieczeństwowy
i pożądany — trasa przechodzi przez `get_owned_portfolio`, więc nie
istnieje endpoint dywidendowy bez weryfikacji własności zasobu
(CLAUDE.md #3.2).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Query

from app.core.deps import PortfolioDep
from app.db.session import DbSession
from app.modules.dividends.schemas import DividendCalendarOut
from app.modules.dividends.service import portfolio_calendar

router = APIRouter(tags=["dividends"])


@router.get("/portfolios/{portfolio_id}/dividends", response_model=DividendCalendarOut)
async def get_portfolio_dividends(
    portfolio: PortfolioDep,
    db: DbSession,
    horizon_days: Annotated[int, Query(ge=1, le=365)] = 90,
) -> DividendCalendarOut:
    """Najbliższe ex-daty dywidend dla pozycji z portfela.

    `horizon_days` ograniczone do roku: dalej w przyszłość żaden dostawca
    nie sięga zapowiedziami, więc szersze okno obiecywałoby dane, których
    nie ma. Domyślne 90 dni to jeden kwartał, czyli typowy odstęp między
    wypłatami spółek amerykańskich.

    „Dziś" liczone w UTC, bo ex-daty są datami kalendarzowymi giełdy
    zdarzenia i przesunięcie o kilka godzin nie zmienia tu nic poza jednym
    granicznym dniem — a wybór strefy serwera byłby równie arbitralny
    i mniej przewidywalny w testach.
    """
    return await portfolio_calendar(
        db,
        portfolio.id,
        today=datetime.now(UTC).date(),
        horizon_days=horizon_days,
    )
