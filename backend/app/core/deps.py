"""Zależności FastAPI współdzielone między modułami.

`get_current_user` weryfikuje access JWT (etap 2, plan krok 12) i wstrzykuje
model `User`. Zależności izolacji zasobowej `get_owned_portfolio` /
`get_owned_holding` (ADR-002, skill `izolacja-danych`) powstają w etapie
3/5, dopiero gdy istnieją tabele `portfolios`/`holdings` — świadomie nie
tutaj.

Zasada na przyszłość: nowy typ zasobu wymagający autoryzacji = nowa
zależność `get_owned_*` w tym pliku, nigdy przyjmowanie gołego ID z path.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Header

from app.core.errors import UnauthorizedError
from app.core.security import decode_access_token
from app.db.session import DbSession
from app.modules.auth.models import User

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

    user = await db.get(User, user_id)
    if user is None:
        raise UnauthorizedError("Użytkownik nie istnieje")
    return user


CurrentUserDep = Annotated[User, Depends(get_current_user)]
