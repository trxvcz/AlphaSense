"""Testy modułu `auth`: rejestracja, logowanie, rotacja refresh tokenu, wylogowanie.

Baza: prawdziwy Postgres (fixture `_clean_auth_tables` w `conftest.py` czyści
tabele przed każdym testem) — bez mocków ORM, zgodnie z docs/konwencje.md.

Test dependency `get_current_user` bez tokenu jest wywołany bezpośrednio
(bez dodawania tymczasowego chronionego endpointu do aplikacji) — moduł
`auth` sam nie ma jeszcze żadnego chronionego endpointu, więc nie ma gdzie
tego przetestować przez HTTP bez rozszerzania zakresu innego modułu.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user
from app.core.errors import UnauthorizedError

EMAIL_A = "usera@example.com"
PASSWORD_A = "correct-password-1"


async def _register(client: AsyncClient, email: str = EMAIL_A, password: str = PASSWORD_A):
    return await client.post("/api/auth/register", json={"email": email, "password": password})


async def _login(client: AsyncClient, email: str = EMAIL_A, password: str = PASSWORD_A):
    return await client.post("/api/auth/login", json={"email": email, "password": password})


async def test_register_login_refresh_logout_happy_path(client: AsyncClient) -> None:
    register_resp = await _register(client)
    assert register_resp.status_code == 201
    body = register_resp.json()
    assert body["email"] == EMAIL_A
    assert "password_hash" not in body
    assert "password" not in body

    login_resp = await _login(client)
    assert login_resp.status_code == 200
    login_body = login_resp.json()
    assert login_body["token_type"] == "bearer"
    assert login_body["access_token"]

    set_cookie_header = login_resp.headers.get("set-cookie", "")
    assert "refresh_token=" in set_cookie_header
    assert "HttpOnly" in set_cookie_header

    refresh_resp = await client.post("/api/auth/refresh")
    assert refresh_resp.status_code == 200
    refresh_body = refresh_resp.json()
    assert refresh_body["access_token"]

    refresh_set_cookie = refresh_resp.headers.get("set-cookie", "")
    assert "refresh_token=" in refresh_set_cookie
    # rotacja musi wydać INNY refresh token niż ten z logowania
    assert refresh_resp.cookies["refresh_token"] != login_resp.cookies["refresh_token"]

    logout_resp = await client.post("/api/auth/logout")
    assert logout_resp.status_code == 204

    logout_set_cookie = logout_resp.headers.get("set-cookie", "")
    assert "refresh_token=" in logout_set_cookie
    assert "Max-Age=0" in logout_set_cookie or "max-age=0" in logout_set_cookie.lower()

    # cookie wyczyszczony po stronie serwera → kolejny refresh już nie działa
    refresh_after_logout = await client.post("/api/auth/refresh")
    assert refresh_after_logout.status_code == 401


async def test_login_with_wrong_password_returns_401(client: AsyncClient) -> None:
    register_resp = await _register(client)
    assert register_resp.status_code == 201

    login_resp = await _login(client, password="wrong-password")
    assert login_resp.status_code == 401
    assert login_resp.json()["error"]["code"] == "unauthorized"


async def test_register_duplicate_email_returns_409(client: AsyncClient) -> None:
    first = await _register(client)
    assert first.status_code == 201

    second = await _register(client)
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "conflict"


async def test_refresh_token_reuse_revokes_whole_chain(client: AsyncClient) -> None:
    register_resp = await _register(client)
    assert register_resp.status_code == 201

    login_resp = await _login(client)
    assert login_resp.status_code == 200
    token1 = login_resp.cookies["refresh_token"]

    first_rotation = await client.post("/api/auth/refresh")
    assert first_rotation.status_code == 200
    token2 = first_rotation.cookies["refresh_token"]
    assert token2 != token1

    # reużycie starego (już rotowanego) tokena → 401, sygnał kradzieży
    reuse_resp = await client.post("/api/auth/refresh", cookies={"refresh_token": token1})
    assert reuse_resp.status_code == 401
    assert reuse_resp.json()["error"]["code"] == "unauthorized"

    # nowy token, wydany chwilę wcześniej, też już nie działa — cały łańcuch unieważniony
    chain_resp = await client.post("/api/auth/refresh", cookies={"refresh_token": token2})
    assert chain_resp.status_code == 401
    assert chain_resp.json()["error"]["code"] == "unauthorized"


async def test_refresh_without_cookie_returns_401(client: AsyncClient) -> None:
    resp = await client.post("/api/auth/refresh")
    assert resp.status_code == 401


async def test_get_current_user_without_header_raises_unauthorized(
    db_session: AsyncSession,
) -> None:
    with pytest.raises(UnauthorizedError):
        await get_current_user(db=db_session, authorization=None)


async def test_get_current_user_with_garbage_token_raises_unauthorized(
    db_session: AsyncSession,
) -> None:
    with pytest.raises(UnauthorizedError):
        await get_current_user(db=db_session, authorization="Bearer garbage-not-a-jwt")
