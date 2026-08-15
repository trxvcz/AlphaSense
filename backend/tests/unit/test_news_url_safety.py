"""Testy odrzucania niebezpiecznych adresów newsów (krok 46, znalezisko z code-review).

Adres newsa pochodzi w całości z cudzego feedu i trafia prosto do `href`
w przeglądarce zalogowanego użytkownika. React **nie** blokuje `javascript:`
ani `data:` w `href` — wypisuje ostrzeżenie w konsoli i renderuje link, więc
jeden wpis w przejętym feedzie wydawcy wystarczyłby do wykonania skryptu
w kontekście sesji.

Walidacja jest przy ingestii, u wszystkich trzech dostawców, dlatego testy
sprawdzają ją zarówno na czystej funkcji, jak i na każdej z trzech ścieżek
osobno — regresja w jednym providerze nie może przejść dlatego, że dwa
pozostałe mają test.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from typing import Any

import httpx
import pytest
import respx

from app.core.cache import get_redis
from app.modules.marketdata.providers.rate_limiter import RateLimiter
from app.modules.news.providers.alphavantage_news import AlphaVantageNewsProvider
from app.modules.news.providers.base import is_safe_http_url
from app.modules.news.providers.finnhub_news import FinnhubNewsProvider
from app.modules.news.providers.rss import RssProvider

_FEED_URL = "https://feed.test/rss.xml"


@pytest.fixture(autouse=True)
async def _cleanup_rate_limiter_keys() -> AsyncGenerator[None, None]:
    yield
    async for key in get_redis().scan_iter("rate_limiter:test-url-safety-*"):
        await get_redis().delete(key)


def _limiter() -> RateLimiter:
    return RateLimiter(f"test-url-safety-{uuid.uuid4().hex}", 60, redis=get_redis())


# --- czysta funkcja ---


@pytest.mark.parametrize(
    "url",
    [
        "https://www.bankier.pl/wiadomosc/WIG20-rekord-1234567.html",
        "http://stooq.pl/n/?f=1",
        # Wielkość liter w schemacie nie ma znaczenia dla przeglądarki
        # i nie może mieć dla nas.
        "HTTPS://www.money.pl/x",
    ],
)
def test_przepuszcza_zwykle_adresy_http(url: str) -> None:
    assert is_safe_http_url(url) is True


@pytest.mark.parametrize(
    "url",
    [
        "javascript:alert(document.cookie)",
        # Wielkość liter i spacja przed dwukropkiem — klasyczne obejścia
        # naiwnego `startswith("javascript:")`.
        "JaVaScRiPt:alert(1)",
        "data:text/html;base64,PHNjcmlwdD5hbGVydCgxKTwvc2NyaXB0Pg==",
        "vbscript:msgbox(1)",
        "file:///etc/passwd",
        # Znak sterujący w środku: przeglądarka usuwa go PRZED interpretacją
        # schematu, więc to jest wykonywalne `javascript:`, mimo że
        # `urlsplit` widzi tu ścieżkę względną bez schematu.
        "java\nscript:alert(1)",
        "java\tscript:alert(1)",
        # Poprawny schemat, ale brak hosta — nie ma dokąd prowadzić.
        "https:///bez-hosta",
        "",
    ],
)
def test_odrzuca_adresy_ktore_nie_sa_zwyklym_linkiem(url: str) -> None:
    assert is_safe_http_url(url) is False


# --- RSS ---


def _rss_body(link: str) -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<rss version="2.0"><channel><title>Feed</title>'
        "<item><title>WIG20 z nowym rekordem</title>"
        f"<link>{link}</link>"
        "<pubDate>Mon, 11 Aug 2026 14:30:00 +0000</pubDate>"
        "</item></channel></rss>"
    )


async def _fetch_rss(link: str) -> list[Any]:
    async with httpx.AsyncClient() as client:
        provider = RssProvider(client, feeds=[_FEED_URL], limiter=_limiter())
        with respx.mock(assert_all_called=True) as router:
            router.get(_FEED_URL).respond(
                text=_rss_body(link), headers={"content-type": "application/rss+xml"}
            )
            return await provider.get_news()


async def test_rss_pomija_wpis_z_niebezpiecznym_linkiem() -> None:
    assert await _fetch_rss("javascript:alert(1)") == []


async def test_rss_przepuszcza_wpis_z_poprawnym_linkiem() -> None:
    """Kontrola negatywna do testu wyżej — gdyby pusta lista brała się
    z zepsutego parsowania feedu, ten test też by padł."""
    items = await _fetch_rss("https://www.bankier.pl/wiadomosc/x-1.html")

    assert len(items) == 1
    assert items[0].url == "https://www.bankier.pl/wiadomosc/x-1.html"


# --- Finnhub ---


async def _fetch_finnhub(url: str) -> list[Any]:
    payload = [
        {
            "headline": "Apple beats estimates",
            "url": url,
            "datetime": 1786285800,
            "summary": "Skrót.",
            "source": "Reuters",
        }
    ]
    async with httpx.AsyncClient() as client:
        provider = FinnhubNewsProvider(client, limiter=_limiter(), api_key="test-key")
        with respx.mock(assert_all_called=True) as router:
            router.get(url__regex=r".*company-news.*").respond(json=payload)
            return await provider.get_news(symbol="AAPL")


async def test_finnhub_pomija_wpis_z_niebezpiecznym_linkiem() -> None:
    """Finnhub jest pośrednikiem — `url` podał wydawca, nie on, więc
    zaufanie do dostawcy niczego tu nie załatwia."""
    assert await _fetch_finnhub("javascript:alert(1)") == []


async def test_finnhub_przepuszcza_wpis_z_poprawnym_linkiem() -> None:
    items = await _fetch_finnhub("https://www.reuters.com/apple")

    assert len(items) == 1


# --- Alpha Vantage ---


async def _fetch_alphavantage(url: str) -> list[Any]:
    payload = {
        "feed": [
            {
                "title": "Apple Downgraded",
                "url": url,
                "time_published": "20260811T143000",
                "summary": "Skrót.",
                "source": "Yahoo Finance",
                "overall_sentiment_score": "0.15",
                "ticker_sentiment": [
                    {
                        "ticker": "AAPL",
                        "relevance_score": "1.000000",
                        "ticker_sentiment_score": "0.1",
                    }
                ],
            }
        ]
    }
    async with httpx.AsyncClient() as client:
        provider = AlphaVantageNewsProvider(client, limiter=_limiter(), api_key="test-key")
        with respx.mock(assert_all_called=True) as router:
            router.get("https://www.alphavantage.co/query").respond(json=payload)
            return await provider.get_news_batch(["AAPL"])


async def test_alphavantage_pomija_wpis_z_niebezpiecznym_linkiem() -> None:
    assert await _fetch_alphavantage("javascript:alert(1)") == []


async def test_alphavantage_przepuszcza_wpis_z_poprawnym_linkiem() -> None:
    items = await _fetch_alphavantage("https://finance.yahoo.com/aapl")

    assert len(items) == 1
