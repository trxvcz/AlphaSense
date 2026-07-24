"""Testy logowania Google (OAuth Authorization Code + PKCE, ADR-005, plan krok 13).

Zero realnych wywołań do Google — nagrywamy odpowiedzi httpx przez `respx`
(docs/konwencje.md: testy dostawców „nagrane odpowiedzi, zero sieci"; brak
tu markera `network`, więc te testy idą w normalnym `pytest -q`/CI).

`GOOGLE_CLIENT_ID`/`GOOGLE_CLIENT_SECRET` są puste w `.env` dev/test — to
nie przeszkadza: Authlib i tak buduje poprawny URL/wymienia kod, bo cały
ruch sieciowy jest przechwycony przez `respx`, więc realny sekret nigdy nie
jest potrzebny do przejścia tych testów. Prawdziwe end-to-end z Google
(prawdziwe `client_id`/`client_secret`, prawdziwy `redirect_uri`
zarejestrowany w Google Cloud Console) zostaje do ręcznej weryfikacji przez
użytkownika — poza zasięgiem testów automatycznych tego kroku.
"""

from __future__ import annotations

from urllib.parse import parse_qs, urlparse

import pytest
import respx
from httpx import AsyncClient, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.models import User
from app.modules.auth.oauth import get_google_client

_METADATA_URL = "https://accounts.google.com/.well-known/openid-configuration"
_AUTHORIZATION_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
_USERINFO_ENDPOINT = "https://openidconnect.googleapis.com/v1/userinfo"

_METADATA = {
    "issuer": "https://accounts.google.com",
    "authorization_endpoint": _AUTHORIZATION_ENDPOINT,
    "token_endpoint": _TOKEN_ENDPOINT,
    "userinfo_endpoint": _USERINFO_ENDPOINT,
    "jwks_uri": "https://www.googleapis.com/oauth2/v3/certs",
}

GOOGLE_EMAIL = "googleuser@example.com"


@pytest.fixture(autouse=True)
def _force_metadata_refetch() -> None:
    """Authlib cache'uje `server_metadata` na kliencie po pierwszym fetchu.

    Klient Google jest singletonem modułu (`oauth.py`) współdzielonym przez
    całą sesję testów — bez tego tylko pierwszy test, który trafi na
    `/google/start`, faktycznie odpytałby (zamockowany) `_METADATA_URL`,
    a kolejne dostałyby dane z cache'u sprzed swojego `respx.mock`.
    """
    get_google_client().server_metadata.pop("_loaded_at", None)


def _mock_metadata(router: respx.MockRouter) -> None:
    router.get(_METADATA_URL).respond(json=_METADATA)


async def test_google_start_redirects_with_state_and_pkce_challenge(
    client: AsyncClient,
) -> None:
    with respx.mock(assert_all_called=False) as router:
        _mock_metadata(router)
        resp = await client.get("/api/auth/google/start", follow_redirects=False)

    assert resp.status_code == 302
    location = resp.headers["location"]
    parsed = urlparse(location)
    assert parsed.netloc == "accounts.google.com"
    query = parse_qs(parsed.query)
    assert query["response_type"] == ["code"]
    assert "state" in query
    assert "code_challenge" in query
    assert query["code_challenge_method"] == ["S256"]

    set_cookie = resp.headers.get("set-cookie", "")
    assert "oauth_state=" in set_cookie
    assert "HttpOnly" in set_cookie


async def test_google_callback_without_state_cookie_returns_401(
    client: AsyncClient,
) -> None:
    resp = await client.get(
        "/api/auth/google/callback", params={"code": "irrelevant", "state": "irrelevant"}
    )
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "unauthorized"


async def test_google_callback_with_mismatched_state_returns_401(
    client: AsyncClient,
) -> None:
    with respx.mock(assert_all_called=False) as router:
        _mock_metadata(router)
        start_resp = await client.get("/api/auth/google/start", follow_redirects=False)
    assert start_resp.status_code == 302

    callback_resp = await client.get(
        "/api/auth/google/callback",
        params={"code": "some-code", "state": "tampered-state-not-matching-cookie"},
        cookies={"oauth_state": start_resp.cookies["oauth_state"]},
    )
    assert callback_resp.status_code == 401
    assert callback_resp.json()["error"]["code"] == "unauthorized"


async def test_google_callback_without_code_returns_401(client: AsyncClient) -> None:
    with respx.mock(assert_all_called=False) as router:
        _mock_metadata(router)
        start_resp = await client.get("/api/auth/google/start", follow_redirects=False)
    location = urlparse(start_resp.headers["location"])
    state = parse_qs(location.query)["state"][0]

    callback_resp = await client.get(
        "/api/auth/google/callback",
        params={"state": state},
        cookies={"oauth_state": start_resp.cookies["oauth_state"]},
    )
    assert callback_resp.status_code == 401


async def test_google_callback_with_provider_error_returns_401(client: AsyncClient) -> None:
    with respx.mock(assert_all_called=False) as router:
        _mock_metadata(router)
        start_resp = await client.get("/api/auth/google/start", follow_redirects=False)

    callback_resp = await client.get(
        "/api/auth/google/callback",
        params={"error": "access_denied", "state": "x"},
        cookies={"oauth_state": start_resp.cookies["oauth_state"]},
    )
    assert callback_resp.status_code == 401


async def _run_full_google_flow(client: AsyncClient, *, email: str = GOOGLE_EMAIL) -> Response:
    """Przechodzi cały flow `/start` → `/callback` z zamockowanym Google."""
    with respx.mock(assert_all_called=False) as router:
        _mock_metadata(router)
        start_resp = await client.get("/api/auth/google/start", follow_redirects=False)
        assert start_resp.status_code == 302
        location = urlparse(start_resp.headers["location"])
        state = parse_qs(location.query)["state"][0]

        router.post(_TOKEN_ENDPOINT).respond(
            json={
                "access_token": "fake-google-access-token",
                "token_type": "Bearer",
                "expires_in": 3600,
                "scope": "openid email profile",
            }
        )
        router.get(_USERINFO_ENDPOINT).respond(
            json={
                "sub": "1234567890",
                "email": email,
                "email_verified": True,
                "name": "Jan Kowalski",
            }
        )

        return await client.get(
            "/api/auth/google/callback",
            params={"code": "fake-code", "state": state},
            cookies={"oauth_state": start_resp.cookies["oauth_state"]},
        )


async def test_google_callback_happy_path_creates_user_and_issues_tokens(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    resp = await _run_full_google_flow(client)

    assert resp.status_code == 200
    body = resp.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]

    set_cookie = resp.headers.get("set-cookie", "")
    assert "refresh_token=" in set_cookie
    assert "HttpOnly" in set_cookie
    # cookie stanu OAuth musi być wyczyszczone po zużyciu
    assert "oauth_state=" in set_cookie

    user = await db_session.scalar(select(User).where(User.email == GOOGLE_EMAIL))
    assert user is not None
    assert user.password_hash is None


async def test_google_callback_upserts_existing_account_by_email(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    first = await _run_full_google_flow(client)
    assert first.status_code == 200

    second = await _run_full_google_flow(client)
    assert second.status_code == 200

    result = await db_session.scalars(select(User).where(User.email == GOOGLE_EMAIL))
    users = result.all()
    assert len(users) == 1


async def test_google_callback_rejects_unverified_email(client: AsyncClient) -> None:
    with respx.mock(assert_all_called=False) as router:
        _mock_metadata(router)
        start_resp = await client.get("/api/auth/google/start", follow_redirects=False)
        location = urlparse(start_resp.headers["location"])
        state = parse_qs(location.query)["state"][0]

        router.post(_TOKEN_ENDPOINT).respond(
            json={"access_token": "tok", "token_type": "Bearer", "expires_in": 3600}
        )
        router.get(_USERINFO_ENDPOINT).respond(
            json={"sub": "1", "email": "unverified@example.com", "email_verified": False}
        )

        resp = await client.get(
            "/api/auth/google/callback",
            params={"code": "fake-code", "state": state},
            cookies={"oauth_state": start_resp.cookies["oauth_state"]},
        )

    assert resp.status_code == 401


async def test_google_callback_maps_token_exchange_failure_to_401(client: AsyncClient) -> None:
    with respx.mock(assert_all_called=False) as router:
        _mock_metadata(router)
        start_resp = await client.get("/api/auth/google/start", follow_redirects=False)
        location = urlparse(start_resp.headers["location"])
        state = parse_qs(location.query)["state"][0]

        router.post(_TOKEN_ENDPOINT).respond(
            400, json={"error": "invalid_grant", "error_description": "Bad code"}
        )

        resp = await client.get(
            "/api/auth/google/callback",
            params={"code": "already-used-code", "state": state},
            cookies={"oauth_state": start_resp.cookies["oauth_state"]},
        )

    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "unauthorized"


async def test_google_login_reclaims_account_pre_registered_by_attacker(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Regresja audytu etap 2, znalezisko WYSOKIE: pre-account-hijack.

    Atakujący rejestruje się hasłem na e-mail ofiary (`/auth/register` nie
    weryfikuje e-maila) i zostawia sobie aktywną sesję (refresh token).
    Kiedy prawdziwy właściciel e-maila loguje się przez Google (e-mail
    zweryfikowany przez Google), backend musi: (1) wyczyścić hasło
    atakującego, żeby stare hasło już nie logowało, i (2) unieważnić WSZYSTKIE
    aktywne refresh tokeny konta, żeby atakujący nie miał trwałej sesji.
    """
    attacker_email = "victim@example.com"
    attacker_password = "attacker-password-123"

    register_resp = await client.post(
        "/api/auth/register", json={"email": attacker_email, "password": attacker_password}
    )
    assert register_resp.status_code == 201

    attacker_login_resp = await client.post(
        "/api/auth/login", json={"email": attacker_email, "password": attacker_password}
    )
    assert attacker_login_resp.status_code == 200
    attacker_refresh_token = attacker_login_resp.cookies["refresh_token"]

    google_resp = await _run_full_google_flow(client, email=attacker_email)
    assert google_resp.status_code == 200

    # dokładnie jedno konto (upsert po e-mailu, nie duplikat)
    result = await db_session.scalars(select(User).where(User.email == attacker_email))
    users = result.all()
    assert len(users) == 1
    assert users[0].password_hash is None

    # stare hasło atakującego już nie działa
    old_password_login = await client.post(
        "/api/auth/login", json={"email": attacker_email, "password": attacker_password}
    )
    assert old_password_login.status_code == 401

    # stary refresh token atakującego (wydany przy rejestracji/loginie) unieważniony
    stale_refresh_resp = await client.post(
        "/api/auth/refresh", cookies={"refresh_token": attacker_refresh_token}
    )
    assert stale_refresh_resp.status_code == 401


async def test_google_account_cannot_log_in_via_password_login(client: AsyncClient) -> None:
    """Konto OAuth-only (`password_hash IS NULL`) nie loguje się przez `/auth/login`."""
    resp = await _run_full_google_flow(client)
    assert resp.status_code == 200

    login_resp = await client.post(
        "/api/auth/login", json={"email": GOOGLE_EMAIL, "password": "whatever-12345"}
    )
    assert login_resp.status_code == 401
    assert login_resp.json()["error"]["code"] == "unauthorized"
