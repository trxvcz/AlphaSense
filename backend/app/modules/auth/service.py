"""Logika domenowa modułu `auth`: rejestracja, logowanie, rotacja refresh
tokenów, logowanie Google (OAuth Authorization Code + PKCE, ADR-005).

Warstwa `routes` woła wyłącznie funkcje z tego pliku, nigdy SQL bezpośrednio
(skill `fastapi-modul`). Wyjątki domenowe z `core/errors.py`, nigdy
`HTTPException` tutaj. Klient OAuth (Authlib) leży w `oauth.py` — ten
plik tylko go woła i upsertuje konto.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from authlib.integrations.base_client import OAuthError
from httpx import HTTPStatusError
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import ConflictError, UnauthorizedError
from app.core.security import (
    create_access_token,
    create_refresh_token,
    hash_password,
    hash_refresh_token,
    verify_password,
)
from app.modules.auth.models import RefreshToken, User
from app.modules.auth.oauth import get_google_client


@dataclass(frozen=True, slots=True)
class TokenPair:
    """Para wydana przy logowaniu/rotacji: access do body, refresh do cookie."""

    access_token: str
    refresh_token: str
    refresh_expires_at: datetime


def normalize_email(email: str) -> str:
    """Normalizuje e-mail przed każdym zapisem/lookupem (`.strip().lower()`).

    Jedno miejsce dla wszystkich ścieżek modułu `auth` (audyt etap 2,
    znalezisko ŚREDNIE) — bez tego `Foo@x.com` i `foo@x.com` tworzyłyby dwa
    różne konta (`register_user`/`authenticate_user`) albo `/auth/google/*`
    nie trafiałoby w konto zarejestrowane hasłem z inną wielkością liter.
    Wołane też z `_upsert_user_by_email` dla e-maila z profilu Google, który
    nie przechodzi przez schemat Pydantic w `schemas.py`.
    """
    return email.strip().lower()


async def register_user(db: AsyncSession, *, email: str, password: str) -> User:
    """Rejestruje nowe konto. `ConflictError` (409), jeśli e-mail już zajęty."""
    email = normalize_email(email)
    existing = await db.scalar(select(User).where(User.email == email))
    if existing is not None:
        raise ConflictError("Konto z tym adresem e-mail już istnieje")

    user = User(email=email, password_hash=hash_password(password))
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def authenticate_user(db: AsyncSession, *, email: str, password: str) -> User:
    """Weryfikuje e-mail/hasło. `UnauthorizedError` (401), jeśli błędne.

    Świadomie ten sam komunikat i kod dla „brak konta", „błędne hasło" i
    „konto OAuth-only bez hasła" (`password_hash is None`) — nie ujawniamy,
    które adresy są zarejestrowane ani jak dane konto powstało.
    """
    email = normalize_email(email)
    user = await db.scalar(select(User).where(User.email == email))
    if (
        user is None
        or user.password_hash is None
        or not verify_password(password, user.password_hash)
    ):
        raise UnauthorizedError("Nieprawidłowy e-mail lub hasło")
    return user


async def issue_token_pair(db: AsyncSession, user: User) -> TokenPair:
    """Wydaje nową parę access+refresh dla `user` i zapisuje refresh w DB."""
    settings = get_settings()
    access_token = create_access_token(user.id)
    raw_refresh, refresh_hash = create_refresh_token()
    expires_at = datetime.now(UTC) + timedelta(days=settings.refresh_token_days)

    db.add(RefreshToken(user_id=user.id, token_hash=refresh_hash, expires_at=expires_at))
    await db.commit()

    return TokenPair(
        access_token=access_token, refresh_token=raw_refresh, refresh_expires_at=expires_at
    )


async def rotate_refresh_token(db: AsyncSession, raw_refresh_token: str) -> TokenPair:
    """Rotuje refresh token: unieważnia stary, wydaje nowy access+refresh.

    Token nieznany lub wygasły → `UnauthorizedError` (401). Reużycie tokena,
    który już ma następcę (`revoked_at` ustawiony) to sygnał kradzieży —
    unieważnia WSZYSTKIE aktywne refresh tokeny tego użytkownika, nie tylko
    ten jeden, i rzuca `UnauthorizedError` (401).
    """
    token_hash = hash_refresh_token(raw_refresh_token)
    # `with_for_update()`: dwa równoczesne żądania z tym samym refresh tokenem
    # muszą się serializować na tym wierszu, żeby oba nie przeszły przez
    # detekcję reużycia (race condition, audyt etap 2, znalezisko NISKIE) —
    # drugie żądanie czeka na commit/rollback pierwszego i widzi już
    # zaktualizowany `revoked_at`.
    token = await db.scalar(
        select(RefreshToken).where(RefreshToken.token_hash == token_hash).with_for_update()
    )

    if token is None:
        raise UnauthorizedError("Nieprawidłowy refresh token")

    if token.revoked_at is not None:
        await _revoke_all_active_tokens(db, user_id=token.user_id)
        await db.commit()
        raise UnauthorizedError("Refresh token już użyty — wszystkie sesje unieważnione")

    now = datetime.now(UTC)
    if token.expires_at < now:
        raise UnauthorizedError("Refresh token wygasł")

    user = await db.get(User, token.user_id)
    if user is None:
        raise UnauthorizedError("Nieprawidłowy refresh token")

    settings = get_settings()
    access_token = create_access_token(user.id)
    raw_new_refresh, new_refresh_hash = create_refresh_token()
    new_expires_at = now + timedelta(days=settings.refresh_token_days)

    new_token = RefreshToken(
        user_id=user.id, token_hash=new_refresh_hash, expires_at=new_expires_at
    )
    db.add(new_token)
    await db.flush()  # potrzebujemy new_token.id przed ustawieniem replaced_by

    token.revoked_at = now
    token.replaced_by = new_token.id
    await db.commit()

    return TokenPair(
        access_token=access_token,
        refresh_token=raw_new_refresh,
        refresh_expires_at=new_expires_at,
    )


async def revoke_refresh_token(db: AsyncSession, raw_refresh_token: str) -> None:
    """Unieważnia refresh token (logout).

    Idempotentne: nieznany albo już unieważniony token to nie błąd — logout
    ma się zawsze powiedzieć „udało się" z punktu widzenia klienta.
    """
    token_hash = hash_refresh_token(raw_refresh_token)
    token = await db.scalar(select(RefreshToken).where(RefreshToken.token_hash == token_hash))
    if token is not None and token.revoked_at is None:
        token.revoked_at = datetime.now(UTC)
        await db.commit()


async def _revoke_all_active_tokens(db: AsyncSession, *, user_id: UUID) -> None:
    """Unieważnia wszystkie aktywne (nie unieważnione) refresh tokeny użytkownika."""
    await db.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=datetime.now(UTC))
    )


@dataclass(frozen=True, slots=True)
class GoogleAuthorizationStart:
    """Wynik `start_google_login`: dokąd przekierować i co zapamiętać w cookie."""

    url: str
    state: str
    code_verifier: str


async def start_google_login(*, redirect_uri: str) -> GoogleAuthorizationStart:
    """Buduje URL autoryzacji Google (Authorization Code + PKCE, ADR-005).

    `state` i `code_verifier` generuje Authlib; nie zapisujemy ich tu po
    stronie serwera (bez sesji, stateless-JWT) — `routes.py` zamyka je
    w podpisanym, krótkotrwałym cookie (`core.security.create_oauth_state_token`)
    i odczytuje z powrotem w `/auth/google/callback`.
    """
    google = get_google_client()
    authorization = await google.create_authorization_url(redirect_uri=redirect_uri)
    return GoogleAuthorizationStart(
        url=authorization["url"],
        state=authorization["state"],
        code_verifier=authorization["code_verifier"],
    )


async def complete_google_login(
    db: AsyncSession, *, code: str, code_verifier: str, redirect_uri: str
) -> User:
    """Wymienia kod Google na token, pobiera profil, upsert konta po e-mailu.

    Żądania do Google idą wyłącznie z backendu (nigdy z frontendu — ADR-005).
    `UnauthorizedError` (401), jeśli wymiana kodu zawiedzie (kod już użyty,
    wygasł, `code_verifier` się nie zgadza) albo Google zwróci e-mail, który
    nie jest zweryfikowany.
    """
    google = get_google_client()
    try:
        token = await google.fetch_access_token(
            redirect_uri=redirect_uri, code=code, code_verifier=code_verifier
        )
    except OAuthError as exc:
        raise UnauthorizedError("Nie udało się wymienić kodu Google na token") from exc

    try:
        profile = await google.userinfo(token=token)
    except HTTPStatusError as exc:
        raise UnauthorizedError("Nie udało się pobrać profilu z Google") from exc

    email = profile.get("email")
    if not email or not profile.get("email_verified", False):
        raise UnauthorizedError("Adres e-mail z Google nie jest zweryfikowany")

    return await _upsert_user_by_email(db, email=email)


async def _upsert_user_by_email(db: AsyncSession, *, email: str) -> User:
    """Znajduje konto po e-mailu albo tworzy nowe konto OAuth-only (bez hasła).

    Dopasowanie wyłącznie po `email`, bez kolumny `google_id`/`oauth_provider`
    (decyzja kroku 13 — prościej, patrz raport).

    Zamknięcie znaleziska WYSOKIE (audyt etap 2, "pre-account-hijack"):
    Google weryfikuje e-mail przed wydaniem profilu (sprawdzone w
    `complete_google_login`), więc w tym miejscu e-mail jest zweryfikowany
    przez zewnętrznego dostawcę. Jeśli istniejące konto na ten e-mail ma
    `password_hash IS NOT NULL`, powstało przez `/auth/register`, który NIE
    weryfikuje e-maila — mógł je założyć ktokolwiek, kto tylko znał adres
    ofiary, i czekać, aż właściciel się zaloguje. W momencie, gdy właściciel
    e-maila potwierdza go przez Google, odbieramy dostęp hasłowy atakującemu:
    czyścimy `password_hash` (hasło atakującego już nie działa) i unieważniamy
    WSZYSTKIE aktywne refresh tokeny konta (ubijamy sesje, które atakujący
    mógł już mieć otwarte) — zanim zwrócimy użytkownika do zalogowania.
    """
    email = normalize_email(email)
    user = await db.scalar(select(User).where(User.email == email))
    if user is not None:
        if user.password_hash is not None:
            user.password_hash = None
            await _revoke_all_active_tokens(db, user_id=user.id)
            await db.commit()
            await db.refresh(user)
        return user

    user = User(email=email, password_hash=None)
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user
