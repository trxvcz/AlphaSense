"""Klient OAuth Google (Authorization Code + PKCE, ADR-005, plan krok 13).

Authlib buduje URL autoryzacji (z `code_challenge`/`code_challenge_method`)
i wymienia kod na token. Świadomie **nie** używamy wysokopoziomowych metod
`StarletteOAuth2App.authorize_redirect`/`authorize_access_token` — te
wymagają `request.session` (`SessionMiddleware` Starlette), a ten projekt
jest stateless-JWT, bez sesji serwerowej. Zamiast tego `service.py` woła
niżej położone `create_authorization_url` / `fetch_access_token` / `userinfo`
i sam zarządza `state`/`code_verifier` w podpisanym, krótkotrwałym cookie
(`core/security.create_oauth_state_token`).

Profil użytkownika pobieramy z `userinfo_endpoint` (OIDC), nie parsujemy
`id_token` — nie potrzebujemy podpisu JWKS Google do tego, czego chcemy się
dowiedzieć (e-mail, weryfikacja e-maila), a to o jedną zależność mniej do
utrzymania w tym kroku.
"""

from __future__ import annotations

from authlib.integrations.starlette_client import OAuth, StarletteOAuth2App

from app.core.config import get_settings

_GOOGLE_METADATA_URL = "https://accounts.google.com/.well-known/openid-configuration"

_oauth = OAuth()
_settings = get_settings()

_oauth.register(
    name="google",
    client_id=_settings.google_client_id,
    client_secret=_settings.google_client_secret,
    server_metadata_url=_GOOGLE_METADATA_URL,
    client_kwargs={
        "scope": "openid email profile",
        # Wymusza PKCE (RFC 7636) niezależnie od tego, czy Google by go
        # wymagał dla tego typu klienta — ADR-005 mówi "Authorization Code
        # + PKCE", nie "Authorization Code, PKCE jeśli wymagany".
        "code_challenge_method": "S256",
    },
)


def get_google_client() -> StarletteOAuth2App:
    """Zwraca zarejestrowany wyżej klient OAuth2 Google (cache Authlib)."""
    client = _oauth.create_client("google")
    if client is None:  # pragma: no cover - zarejestrowany raz, wyżej w tym module
        raise RuntimeError("Klient OAuth Google nie jest zarejestrowany")
    return client
