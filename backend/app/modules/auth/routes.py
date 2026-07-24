"""Routing modułu `auth`: rejestracja, logowanie, rotacja refresh tokenu,
wylogowanie, logowanie Google (OAuth Authorization Code + PKCE, ADR-005,
plan krok 13).

Warstwa routes: tylko walidacja wejścia (Pydantic/query params), obsługa
cookie i wywołanie `service` — zero SQL i zero wywołań HTTP do Google
bezpośrednio tutaj (to woła `service`/`oauth.py`), zero logiki domenowej
(skill `fastapi-modul`). Weryfikacja `state` cookie kontra `state` z query
Google jest sprawdzeniem wejścia HTTP (jak brak cookie `refresh_token` w
`/auth/refresh` poniżej), nie logiką domenową — stąd żyje tutaj, nie
w `service.py`.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Cookie, Query, Request, Response, status
from fastapi.responses import RedirectResponse

from app.core.config import get_settings
from app.core.errors import UnauthorizedError
from app.core.rate_limit import AUTH_RATE_LIMIT, limiter
from app.core.security import create_oauth_state_token, decode_oauth_state_token
from app.db.session import DbSession
from app.modules.auth import service
from app.modules.auth.schemas import AccessTokenOut, LoginIn, RegisterIn, UserOut

router = APIRouter(prefix="/auth", tags=["auth"])

_REFRESH_COOKIE_NAME = "refresh_token"
# Cookie ograniczone do ścieżek auth — nie musi wędrować z każdym żądaniem
# do /api/portfolios/... itd.
_REFRESH_COOKIE_PATH = "/api/auth"

_OAUTH_STATE_COOKIE_NAME = "oauth_state"
# Tylko flow Google — nie ma powodu, żeby to cookie wędrowało dalej.
_OAUTH_STATE_COOKIE_PATH = "/api/auth/google"
_OAUTH_STATE_COOKIE_MAX_AGE_SECONDS = 10 * 60

RefreshCookie = Annotated[str | None, Cookie(alias=_REFRESH_COOKIE_NAME)]
OAuthStateCookie = Annotated[str | None, Cookie(alias=_OAUTH_STATE_COOKIE_NAME)]


def _set_refresh_cookie(response: Response, raw_refresh_token: str) -> None:
    """Ustawia rotowany refresh token w httpOnly cookie (ADR-005)."""
    settings = get_settings()
    response.set_cookie(
        key=_REFRESH_COOKIE_NAME,
        value=raw_refresh_token,
        httponly=True,
        secure=settings.env != "dev",
        samesite="lax",
        path=_REFRESH_COOKIE_PATH,
        max_age=settings.refresh_token_days * 24 * 3600,
    )


def _set_oauth_state_cookie(response: Response, *, state: str, code_verifier: str) -> None:
    """Zamyka `state`+`code_verifier` w podpisanym, krótkotrwałym cookie.

    Zamiennik `SessionMiddleware` Starlette — ten projekt jest stateless-JWT,
    bez sesji serwerowej (patrz `oauth.py`).
    """
    settings = get_settings()
    token = create_oauth_state_token(state=state, code_verifier=code_verifier)
    response.set_cookie(
        key=_OAUTH_STATE_COOKIE_NAME,
        value=token,
        httponly=True,
        secure=settings.env != "dev",
        samesite="lax",
        path=_OAUTH_STATE_COOKIE_PATH,
        max_age=_OAUTH_STATE_COOKIE_MAX_AGE_SECONDS,
    )


@router.post("/register", status_code=status.HTTP_201_CREATED, response_model=UserOut)
@limiter.limit(AUTH_RATE_LIMIT)
async def register(request: Request, body: RegisterIn, db: DbSession) -> UserOut:
    """Rejestruje nowe konto. 409, jeśli e-mail już zajęty.

    Limit ostrzejszy niż globalny (`AUTH_RATE_LIMIT`, `core/rate_limit.py`)
    — bez tego endpoint jest wygodnym celem do zalewania rejestracjami.
    """
    user = await service.register_user(db, email=body.email, password=body.password)
    return UserOut.model_validate(user)


@router.post("/login", response_model=AccessTokenOut)
@limiter.limit(AUTH_RATE_LIMIT)
async def login(
    request: Request, body: LoginIn, db: DbSession, response: Response
) -> AccessTokenOut:
    """Loguje, wydaje access token w body i refresh token w httpOnly cookie.

    Limit ostrzejszy niż globalny (`AUTH_RATE_LIMIT`, `core/rate_limit.py`)
    — chroni przed brute-force zgadywaniem hasła.
    """
    user = await service.authenticate_user(db, email=body.email, password=body.password)
    token_pair = await service.issue_token_pair(db, user)
    _set_refresh_cookie(response, token_pair.refresh_token)
    return AccessTokenOut(access_token=token_pair.access_token)


@router.post("/refresh", response_model=AccessTokenOut)
async def refresh(
    db: DbSession,
    response: Response,
    refresh_token: RefreshCookie = None,
) -> AccessTokenOut:
    """Rotuje refresh token z cookie, zwraca nowy access token.

    Reużycie tokena już unieważnionego przez wcześniejszą rotację unieważnia
    cały łańcuch refresh tokenów użytkownika (`service.rotate_refresh_token`)
    i kończy się 401.
    """
    if refresh_token is None:
        raise UnauthorizedError("Brak refresh tokenu")

    token_pair = await service.rotate_refresh_token(db, refresh_token)
    _set_refresh_cookie(response, token_pair.refresh_token)
    return AccessTokenOut(access_token=token_pair.access_token)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    db: DbSession,
    response: Response,
    refresh_token: RefreshCookie = None,
) -> None:
    """Unieważnia refresh token po stronie serwera i czyści cookie."""
    if refresh_token is not None:
        await service.revoke_refresh_token(db, refresh_token)
    response.delete_cookie(key=_REFRESH_COOKIE_NAME, path=_REFRESH_COOKIE_PATH)


@router.get("/google/start")
async def google_start() -> RedirectResponse:
    """Przekierowuje do Google (Authorization Code + PKCE, ADR-005).

    `state`/`code_verifier` generuje Authlib (`service.start_google_login`);
    backend je zamyka w podpisanym, krótkotrwałym cookie zamiast sesji
    serwerowej i odczytuje z powrotem w `/auth/google/callback`.
    """
    settings = get_settings()
    authorization = await service.start_google_login(redirect_uri=settings.google_redirect_uri)
    redirect = RedirectResponse(authorization.url, status_code=status.HTTP_302_FOUND)
    _set_oauth_state_cookie(
        redirect, state=authorization.state, code_verifier=authorization.code_verifier
    )
    return redirect


@router.get("/google/callback", response_model=AccessTokenOut)
async def google_callback(
    db: DbSession,
    response: Response,
    code: Annotated[str | None, Query()] = None,
    state: Annotated[str | None, Query()] = None,
    error: Annotated[str | None, Query()] = None,
    oauth_state: OAuthStateCookie = None,
) -> AccessTokenOut:
    """Odbiera powrót z Google, wymienia kod na token, loguje/tworzy konto.

    Weryfikuje `state` z query stringu Google kontra `state` zamknięty
    w cookie `oauth_state` — niezgodność albo brak jednego z nich to 401
    (możliwy CSRF albo wygasła/nieistniejąca sesja logowania). Wydaje
    własną parę access+refresh tak jak `/auth/login`.
    """
    if error is not None:
        raise UnauthorizedError("Logowanie Google odrzucone lub przerwane")
    if code is None or state is None:
        raise UnauthorizedError("Brak parametrów odpowiedzi Google")
    if oauth_state is None:
        raise UnauthorizedError("Brak stanu OAuth — sesja logowania wygasła lub nie istnieje")

    expected_state, code_verifier = decode_oauth_state_token(oauth_state)
    if expected_state != state:
        raise UnauthorizedError("Niezgodny parametr state — możliwy CSRF")

    settings = get_settings()
    user = await service.complete_google_login(
        db,
        code=code,
        code_verifier=code_verifier,
        redirect_uri=settings.google_redirect_uri,
    )
    token_pair = await service.issue_token_pair(db, user)
    _set_refresh_cookie(response, token_pair.refresh_token)
    response.delete_cookie(key=_OAUTH_STATE_COOKIE_NAME, path=_OAUTH_STATE_COOKIE_PATH)
    return AccessTokenOut(access_token=token_pair.access_token)
