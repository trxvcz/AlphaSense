"""Klucz API nie może wyciec przez komunikat wyjątku HTTP.

`httpx` wkleja pełny URL — razem z query stringiem — do treści
`HTTPStatusError`. Ponieważ wszyscy dostawcy Alpha Vantage/Finnhub podają
klucz właśnie w query stringu, każdy błędny status wysyłałby sekret do logu
i do Sentry (CLAUDE.md #3.9).
"""

from __future__ import annotations

import httpx
import pytest
import respx

from app.modules.marketdata.providers.http_client import get_with_backoff

_URL = "https://example.test/query"
_SECRET = "SUPER-SECRET-KEY"


class _NoBackoff:
    async def backoff(self, attempt: int) -> None:  # pragma: no cover - nieużywane
        raise AssertionError("backoff nie powinien być wołany bez HTTP 429")


@respx.mock
@pytest.mark.parametrize("param", ["apikey", "token"])
async def test_klucz_api_nie_trafia_do_komunikatu_bledu(param: str) -> None:
    respx.get(_URL).mock(return_value=httpx.Response(500, text="boom"))

    async with httpx.AsyncClient() as client:
        with pytest.raises(httpx.HTTPStatusError) as excinfo:
            await get_with_backoff(
                client,
                _URL,
                params={"function": "DIVIDENDS", param: _SECRET},
                limiter=_NoBackoff(),
                request_timeout=5.0,
            )

    message = str(excinfo.value)
    assert _SECRET not in message
    assert "REDACTED" in message
    # Reszta URL-a zostaje — bez niej log przestaje mówić, co się zepsuło.
    assert "function=DIVIDENDS" in message
    assert _SECRET not in str(excinfo.value.request.url)


@respx.mock
async def test_odpowiedz_bez_sekretu_zachowuje_pelny_url() -> None:
    respx.get(_URL).mock(return_value=httpx.Response(404))

    async with httpx.AsyncClient() as client:
        with pytest.raises(httpx.HTTPStatusError) as excinfo:
            await get_with_backoff(
                client,
                _URL,
                params={"s": "wig20"},
                limiter=_NoBackoff(),
                request_timeout=5.0,
            )

    assert "s=wig20" in str(excinfo.value)
