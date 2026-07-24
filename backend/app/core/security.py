"""Bezpieczeństwo: hashowanie haseł i tokeny JWT (ADR-005).

argon2id (argon2-cffi) do haseł użytkownika. JWT HS256 (PyJWT) do access
tokenów. Refresh tokeny to losowy string (`secrets.token_urlsafe`) — nie
hasło użytkownika, więc nie argon2: liczy się szybkość lookupu w DB przy
każdym `/auth/refresh`, a nie odporność na offline brute-force. Surowy
refresh token trafia tylko do httpOnly cookie klienta; w bazie leży
wyłącznie jego hash sha256 (`refresh_tokens.token_hash`).
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from app.core.config import get_settings
from app.core.errors import UnauthorizedError

_password_hasher = PasswordHasher()

_JWT_ALGORITHM = "HS256"

# Okno na cały OAuth Google round-trip (przekierowanie do Google + powrót na
# `/auth/google/callback`) — na tyle krótkie, że nie ma sensu wydzielać do
# `Settings` (ADR-005: PKCE po stronie backendu, krok 13).
_OAUTH_STATE_MINUTES = 10


def hash_password(plain_password: str) -> str:
    """Hashuje hasło argon2id (parametry domyślne biblioteki są OK na start)."""
    return _password_hasher.hash(plain_password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Weryfikuje hasło wobec hasha argon2id. Nigdy nie loguje ani hasła, ani hasha."""
    try:
        return _password_hasher.verify(hashed_password, plain_password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def create_access_token(user_id: UUID) -> str:
    """Tworzy access token JWT: `sub`=user_id, `exp`=teraz+`access_token_minutes`."""
    settings = get_settings()
    now = datetime.now(UTC)
    payload = {
        "sub": str(user_id),
        "iat": now,
        "exp": now + timedelta(minutes=settings.access_token_minutes),
    }
    return jwt.encode(payload, settings.secret_key, algorithm=_JWT_ALGORITHM)


def create_refresh_token() -> tuple[str, str]:
    """Tworzy nowy refresh token.

    Zwraca `(raw_token, token_hash)`: `raw_token` trafia do httpOnly cookie
    klienta i nigdy nie jest zapisywany, `token_hash` (sha256) trafia do
    kolumny `refresh_tokens.token_hash`.
    """
    raw_token = secrets.token_urlsafe(32)
    return raw_token, hash_refresh_token(raw_token)


def hash_refresh_token(raw_token: str) -> str:
    """Hashuje surowy refresh token do lookupu w DB (sha256 — szybki lookup, nie hasło)."""
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def create_oauth_state_token(*, state: str, code_verifier: str) -> str:
    """Podpisuje `state` + PKCE `code_verifier` do krótkotrwałego cookie.

    Zamiast sesji serwerowej (ten projekt jest stateless-JWT, ADR-005)
    zapisujemy je w httpOnly cookie klienta jako podpisany JWT — Google nie
    widzi tego tokenu, wraca tylko `state` w query stringu, które porównujemy
    z tym, co odszyfrujemy z cookie w `/auth/google/callback`.
    """
    settings = get_settings()
    now = datetime.now(UTC)
    payload = {
        "typ": "oauth_state",
        "state": state,
        "code_verifier": code_verifier,
        "iat": now,
        "exp": now + timedelta(minutes=_OAUTH_STATE_MINUTES),
    }
    return jwt.encode(payload, settings.secret_key, algorithm=_JWT_ALGORITHM)


def decode_oauth_state_token(token: str) -> tuple[str, str]:
    """Odwraca `create_oauth_state_token`, zwraca `(state, code_verifier)`.

    `UnauthorizedError` przy braku podpisu, wygaśnięciu (round-trip do Google
    trwał zbyt długo) albo nieprawidłowym kształcie payloadu.
    """
    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[_JWT_ALGORITHM])
    except jwt.PyJWTError as exc:
        raise UnauthorizedError("Nieprawidłowy lub wygasły stan OAuth") from exc

    if payload.get("typ") != "oauth_state":
        raise UnauthorizedError("Nieprawidłowy stan OAuth")

    state = payload.get("state")
    code_verifier = payload.get("code_verifier")
    if not isinstance(state, str) or not isinstance(code_verifier, str):
        raise UnauthorizedError("Nieprawidłowy stan OAuth")
    return state, code_verifier


def decode_access_token(token: str) -> UUID:
    """Dekoduje i weryfikuje access token JWT, zwraca `user_id`.

    Rzuca `UnauthorizedError` (401) przy braku podpisu, wygaśnięciu albo
    nieprawidłowym `sub` — mapowanie na HTTP siedzi w jednym miejscu
    (`app.main.domain_error_handler`), nie tutaj.
    """
    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[_JWT_ALGORITHM])
    except jwt.PyJWTError as exc:
        raise UnauthorizedError("Nieprawidłowy lub wygasły token") from exc

    subject = payload.get("sub")
    if not isinstance(subject, str):
        raise UnauthorizedError("Nieprawidłowy token")
    try:
        return UUID(subject)
    except ValueError as exc:
        raise UnauthorizedError("Nieprawidłowy token") from exc
