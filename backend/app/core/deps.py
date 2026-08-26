"""Zależności FastAPI współdzielone między modułami.

`get_current_user` weryfikuje access JWT (etap 2, plan krok 12) i wstrzykuje
model `User`. `get_owned_portfolio`/`get_owned_holding` (ADR-002, skill
`izolacja-danych`) powstają tutaj w etapie 5 (plan krok 25) — pierwsi
konsumenci to `modules/portfolio/routes.py`.

Zasada na przyszłość: nowy typ zasobu wymagający autoryzacji = nowa
zależność `get_owned_*` w tym pliku, nigdy przyjmowanie gołego ID z path.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import Depends, Header
from sqlalchemy import select

from app.core.errors import NotFoundError, UnauthorizedError
from app.core.security import decode_access_token
from app.db.rls import bind_session_user
from app.db.session import DbSession
from app.modules.auth.models import User
from app.modules.portfolio.models import Holding, Portfolio
from app.modules.tags.models import Tag
from app.modules.watchlist.models import Watchlist

_BEARER_PREFIX = "Bearer "


async def get_current_user(
    db: DbSession,
    authorization: Annotated[str | None, Header()] = None,
) -> User:
    """Zależność wstrzykująca zalogowanego użytkownika na podstawie access JWT.

    Czyta nagłówek `Authorization: Bearer <token>`, dekoduje go i ładuje
    `User` z bazy. Rzuca `UnauthorizedError` (401), jeśli nagłówek jest
    nieobecny/źle sformatowany, token jest nieprawidłowy/wygasły albo
    użytkownik, do którego się odnosi, już nie istnieje.
    """
    if authorization is None or not authorization.startswith(_BEARER_PREFIX):
        raise UnauthorizedError("Brak tokenu uwierzytelniającego")

    token = authorization.removeprefix(_BEARER_PREFIX).strip()
    user_id = decode_access_token(token)

    # ADR-002 warstwa 3 (krok 44): kontekst RLS ustawiamy **przed** pierwszym
    # odczytem danych użytkownika i tylko tutaj — to jedyne miejsce w
    # aplikacji, które wie, kto pyta. Identyfikator pochodzi z podpisanego
    # tokenu, nie ze ścieżki żądania.
    await bind_session_user(db, user_id)

    user = await db.get(User, user_id)
    if user is None:
        raise UnauthorizedError("Użytkownik nie istnieje")
    return user


CurrentUserDep = Annotated[User, Depends(get_current_user)]


async def get_owned_portfolio(
    portfolio_id: UUID,
    user: CurrentUserDep,
    db: DbSession,
) -> Portfolio:
    """Zależność zasobowa dla tras `/portfolios/{portfolio_id}...`.

    Wzorzec skilla `izolacja-danych`: filtr `Portfolio.user_id == user.id` w
    samym zapytaniu (nie osobne `SELECT` + porównanie w Pythonie) — cudzy
    portfel (albo nieistniejące `portfolio_id`) to zawsze `NotFoundError`
    (404), nigdy 403, żeby nie zdradzać istnienia zasobu innego użytkownika.
    """
    portfolio = await db.scalar(
        select(Portfolio).where(Portfolio.id == portfolio_id, Portfolio.user_id == user.id)
    )
    if portfolio is None:
        raise NotFoundError("Nie znaleziono portfela")
    return portfolio


PortfolioDep = Annotated[Portfolio, Depends(get_owned_portfolio)]


async def get_owned_holding(
    holding_id: UUID,
    user: CurrentUserDep,
    db: DbSession,
) -> Holding:
    """Zależność zasobowa dla tras `/holdings/{holding_id}`.

    `Holding` nie ma własnej kolumny `user_id` — własność weryfikuje `JOIN`
    z `Portfolio` (jedyny sposób, w jaki pozycja jest powiązana z
    użytkownikiem). Ten sam wzorzec 404-zawsze co `get_owned_portfolio`.
    """
    holding = await db.scalar(
        select(Holding)
        .join(Portfolio, Holding.portfolio_id == Portfolio.id)
        .where(Holding.id == holding_id, Portfolio.user_id == user.id)
    )
    if holding is None:
        raise NotFoundError("Nie znaleziono pozycji")
    return holding


HoldingDep = Annotated[Holding, Depends(get_owned_holding)]


async def get_owned_watchlist(
    watchlist_id: UUID,
    user: CurrentUserDep,
    db: DbSession,
) -> Watchlist:
    """Zależność zasobowa dla tras `/watchlists/{watchlist_id}...` (krok 43).

    Ten sam wzorzec co `get_owned_portfolio`: filtr własności w samym
    zapytaniu i **404 zawsze**, nigdy 403 — cudza watchlista ma być
    nieodróżnialna od nieistniejącej (skill `izolacja-danych`).
    """
    watchlist = await db.scalar(
        select(Watchlist).where(Watchlist.id == watchlist_id, Watchlist.user_id == user.id)
    )
    if watchlist is None:
        raise NotFoundError("Nie znaleziono listy obserwowanych")
    return watchlist


WatchlistDep = Annotated[Watchlist, Depends(get_owned_watchlist)]


async def get_owned_tag(
    tag_id: UUID,
    user: CurrentUserDep,
    db: DbSession,
) -> Tag:
    """Zależność zasobowa dla tras `/tags/{tag_id}...` (krok 43).

    Tag należy do użytkownika, mimo że wskazuje na globalne `assets` —
    dlatego autoryzacja idzie po `tags.user_id`, a nie po aktywie. Gdyby
    szła po aktywie, każdy widziałby, jak inni oznaczyli te same spółki.
    """
    tag = await db.scalar(select(Tag).where(Tag.id == tag_id, Tag.user_id == user.id))
    if tag is None:
        raise NotFoundError("Nie znaleziono tagu")
    return tag


TagDep = Annotated[Tag, Depends(get_owned_tag)]
